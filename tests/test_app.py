import json
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import FakeWeb, model_reply, response, telegram_routes

from pocketagent import config as cfg
from pocketagent.app import App, PanelError
from pocketagent.config import BrainConfig, Config
from pocketagent.llm import PROVIDERS
from pocketagent.oauth import challenge_for


def make_app(*routes):
    web = FakeWeb(*routes)
    return App(Config(), http=web), web


def wait_for(job, app):
    assert app.jobs.get(job["id"]).done.wait(5)
    return app.job(job["id"])


# ---------- step 1: the brain ----------
def test_saving_a_key_checks_it_and_lists_the_models():
    app, web = make_app(("GET", "api.groq.com/openai/v1/models", response(
        {"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "whisper-large-v3"}]})))
    result = app.save_key("groq", "  gsk_test  ")
    assert [m["id"] for m in result["models"]] == ["llama-3.3-70b-versatile"]
    assert app.config.keys["groq"] == "gsk_test" and cfg.load().keys["groq"] == "gsk_test"
    assert web.requests[0][2]["headers"]["Authorization"] == "Bearer gsk_test"


def test_a_rejected_key_is_not_saved():
    app, _ = make_app(("GET", "/models", response({"error": "invalid key"}, 401)))
    with pytest.raises(PanelError, match="rejected"):
        app.save_key("groq", "wrong")
    assert "groq" not in app.config.keys


def test_custom_provider_needs_an_address_and_keeps_the_key_even_without_a_model_list():
    app, _ = make_app()      # this server has no /models endpoint
    with pytest.raises(PanelError):
        app.save_key("custom", "k")
    assert app.save_key("custom", "k", base_url="http://192.168.1.5:11434/v1/")["models"] == []
    assert app.config.custom_url == "http://192.168.1.5:11434/v1"


def test_brains_are_tested_when_added_and_keep_the_users_order():
    app, _ = make_app(("POST", "/chat/completions", model_reply))
    app.config.keys.update({"groq": "g", "gemini": "m"})
    added = app.add_brain("groq", "llama-3.3-70b-versatile")
    assert added["native_tools"] is True and added["answer"] == "OK"
    app.add_brain("gemini", "gemini-2.5-flash")
    assert [b["label"] for b in app.state()["brains"]] == ["Groq · llama-3.3-70b-versatile",
                                                         "Gemini · gemini-2.5-flash"]
    app.move_brain(1, -1)
    assert app.config.brain.provider == "gemini" and cfg.load().brain.provider == "gemini"
    app.remove_brain(0)
    assert [b.provider for b in app.config.brains()] == ["groq"]


def test_a_brain_that_needs_a_key_cannot_be_added_without_one():
    app, _ = make_app()
    with pytest.raises(PanelError, match="key"):
        app.add_brain("cerebras", "gpt-oss-120b")


def test_a_brain_that_does_not_answer_is_not_added():
    app, _ = make_app(("POST", "/chat/completions", response({"error": "model not found"}, 404)))
    app.config.keys["groq"] = "g"
    with pytest.raises(PanelError, match="404"):
        app.add_brain("groq", "no-such-model")
    assert app.config.brains() == []


def test_the_panel_state_never_contains_whole_keys():
    app, _ = make_app()
    app.config.keys["groq"] = "gsk_abcdefghijklmnop"
    state = app.state()
    assert "gsk_abcdefghijklmnop" not in json.dumps(state)
    groq = next(p for p in state["providers"] if p["id"] == "groq")
    assert groq["has_key"] and groq["key_hint"] == "gsk_…mnop"
    assert groq["key_url"] == PROVIDERS["groq"].key_url


def test_openrouter_sign_in_without_copying_a_key():
    app, web = make_app(("POST", "openrouter.ai/api/v1/auth/keys", response({"key": "sk-or-v1-new"})))
    url = app.openrouter_start("http://localhost:8765/oauth/openrouter")
    challenge = parse_qs(urlparse(url).query)["code_challenge"][0]
    app.openrouter_finish("the-code")
    sent = web.requests[-1][2]["json"]
    assert sent["code"] == "the-code" and challenge_for(sent["code_verifier"]) == challenge
    assert app.config.keys["openrouter"] == "sk-or-v1-new"
    with pytest.raises(PanelError):
        app.openrouter_finish("the-code")          # a login can only be finished once


# ---------- step 2: Telegram ----------
def test_telegram_connects_the_first_person_who_presses_start():
    app, web = make_app(*telegram_routes())
    info = app.telegram_connect(" 123:ABC ")
    assert info == {"username": "aykut_agent_bot", "link": "https://t.me/aykut_agent_bot"}
    app.telegram_thread.join(5)
    assert app.config.telegram.owner_chat_id == 111            # not 666, who wrote before the setup
    assert cfg.load().telegram.token == "123:ABC"
    assert app.state()["telegram"] == {"status": "connected", "connected": True,
                                       "username": "aykut_agent_bot", "link": "https://t.me/aykut_agent_bot"}
    assert any(url.endswith("/sendMessage") and kw["json"]["chat_id"] == 111 for _, url, kw in web.requests)


def test_a_wrong_telegram_token_is_refused():
    app, _ = make_app(("GET", "/getMe", response({"ok": False, "description": "Unauthorized"})))
    with pytest.raises(PanelError, match="token"):
        app.telegram_connect("bad")
    assert not app.config.telegram_ready


# ---------- step 3: name; chat ----------
def test_name_and_personality_are_saved_in_identity_json(home):
    app, _ = make_app()
    app.set_identity("  Robi ", "Short, friendly answers.")
    assert app.state()["identity"] == {"name": "Robi", "personality": "Short, friendly answers."}
    assert json.loads((home / "memory" / "identity.json").read_text(encoding="utf-8"))["name"] == "Robi"
    with pytest.raises(PanelError):
        app.set_identity("   ")


def test_panel_chat_runs_as_a_job_and_says_which_brain_answered():
    app, _ = make_app(("POST", "/chat/completions", response({"choices": [{"message": {"content": "Merhaba!"}}]})))
    app.config.set_brains([BrainConfig("groq", PROVIDERS["groq"].base_url, "llama")])
    app.config.keys["groq"] = "g"
    job = wait_for(app.chat("Selam"), app)
    assert job["status"] == "done"
    assert job["result"] == {"text": "Merhaba!", "brain": "Groq · llama", "tools": [], "skipped": [],
                             "files": []}
    assert app.history()[-2:] == [{"role": "user", "content": "Selam"}, {"role": "assistant", "content": "Merhaba!"}]


def test_chat_without_a_brain_fails_politely():
    app, _ = make_app()
    job = wait_for(app.chat("hello"), app)
    assert job["status"] == "failed" and "panel" in job["error"]


# ---------- computer use, approvals, stop ----------
def test_computer_use_is_off_until_the_user_turns_it_on(home):
    app, _ = make_app()
    assert app.state()["computer_use"] is False
    app.set_computer_use(True)
    assert app.config.computer_use and cfg.load().computer_use
    assert app.runtime.audit.recent()[-1]["event"] == "computer_use"


def test_stop_cancels_jobs_denies_approvals_and_turns_computer_use_off(home):
    import threading
    from pocketagent.approvals import Action, Stopped
    app, _ = make_app()
    app.set_computer_use(True)
    release = threading.Event()
    app.jobs.submit("busy", release.wait)
    waiting = app.jobs.submit("later", lambda: "never")
    outcome = []

    def turn(generation=app.runtime.approvals.generation):
        try:
            app.runtime.approvals.request(Action("shell", "x", {"command": "dir"}, scope={"command": "dir"}),
                                          generation=generation)
        except Stopped:
            outcome.append("stopped")
    worker = threading.Thread(target=turn)
    worker.start()
    while not app.state()["approvals"]:
        pass
    summary = app.emergency_stop("panel")
    worker.join(5)
    release.set()
    assert summary["jobs"] == 1 and summary["approvals"] == 1
    assert waiting.status == "cancelled" and outcome == ["stopped"]
    assert app.config.computer_use is False and cfg.load().computer_use is False
    assert any(e["event"] == "stop" for e in app.runtime.audit.recent())


def test_approvals_and_rules_from_the_panel(home):
    import threading
    from pocketagent.approvals import Action
    app, _ = make_app()
    app.set_computer_use(True)
    action = Action("shell", "Run", {"command": "git status"}, scope={"command": "git status"})
    result = []
    worker = threading.Thread(target=lambda: result.append(app.runtime.approvals.request(action)))
    worker.start()
    while not app.state()["approvals"]:
        pass
    pending = app.state()["approvals"][0]
    assert pending["params"] == {"command": "git status"} and pending["can_remember"]
    app.answer_approval(pending["id"], True, True)
    worker.join(5)
    rules = app.state()["rules"]
    assert result == ["approved"] and rules[0]["scope"] == {"command": "git status"}
    app.delete_rule(rules[0]["id"])
    assert app.state()["rules"] == []
    with pytest.raises(PanelError):
        app.delete_rule(rules[0]["id"])


# ---------- OpenRouter's free models ----------
def free_catalog(*models):
    """An OpenRouter model list: (id, context, tools) for free text models, plus one paid model."""
    data = [{"id": mid, "pricing": {"prompt": "0", "completion": "0"}, "context_length": context,
             "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
             "supported_parameters": ["tools"] if tools else []} for mid, context, tools in models]
    data.append({"id": "openai/gpt-5", "pricing": {"prompt": "0.00001", "completion": "0.00001"},
                 "context_length": 400000, "supported_parameters": ["tools"],
                 "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}})
    return ("GET", "openrouter.ai/api/v1/models", response({"data": data}))


ULTRA = ("nvidia/nemotron-3-ultra-550b-a55b:free", 1000000, True)
INKLING = ("thinkingmachines/inkling:free", 1048576, True)
GEMMA = ("google/gemma-4-31b-it:free", 262144, True)
NO_TOOLS = ("liquid/lfm-2.5-2.6b:free", 65536, False)
ROUTER = ("openrouter/free", 200000, True)


def test_free_models_are_added_as_fallbacks_biggest_context_first(home):
    app, _ = make_app(free_catalog(GEMMA, ULTRA, NO_TOOLS, INKLING, ROUTER))
    app.config.keys["openrouter"] = "sk-or"
    app.config.set_brains([BrainConfig("groq", PROVIDERS["groq"].base_url, "llama")])      # chosen by hand
    result = app.sync_free_models(count=2, min_context=500000)
    assert [b.model for b in app.config.brains()] == ["llama", INKLING[0], ULTRA[0], "openrouter/free"]
    assert all(b.auto and b.free and b.native_tools for b in app.config.brains()[1:])
    assert result["added"] == [INKLING[0], ULTRA[0], "openrouter/free"] and result["removed"] == []
    assert cfg.load().free_sync["last"]


def test_a_new_sync_replaces_models_that_are_no_longer_free(home):
    app, web = make_app(free_catalog(ULTRA, INKLING, ROUTER))
    app.config.keys["openrouter"] = "sk-or"
    app.sync_free_models(count=2, min_context=0)
    web.routes[0] = free_catalog(ULTRA, GEMMA, ROUTER)         # Inkling is gone, Gemma is new
    result = app.sync_free_models(count=2, min_context=0)
    assert [b.model for b in app.config.brains()] == [ULTRA[0], GEMMA[0], "openrouter/free"]
    assert result["removed"] == [INKLING[0]] and result["added"] == [GEMMA[0]]


def test_moving_an_automatic_brain_keeps_it_and_removing_one_keeps_it_out(home):
    app, _ = make_app(free_catalog(ULTRA, INKLING, GEMMA))
    app.config.keys["openrouter"] = "sk-or"
    app.sync_free_models(count=3, min_context=0)
    app.move_brain(1, -1)                                       # ULTRA to the top: now chosen by hand
    assert app.config.brain.model == ULTRA[0] and not app.config.brain.auto
    app.remove_brain(2)                                         # Gemma: do not bring it back
    app.sync_free_models(count=3, min_context=0)
    assert [b.model for b in app.config.brains()] == [ULTRA[0], INKLING[0]]


def test_free_sync_needs_openrouter(home):
    app, _ = make_app(free_catalog(ULTRA))
    with pytest.raises(PanelError, match="OpenRouter"):
        app.sync_free_models()


def test_a_busy_free_model_is_still_added(home):
    app, _ = make_app(free_catalog(ULTRA), ("POST", "/chat/completions", response({"error": "rate-limited upstream"}, 429)))
    app.config.keys["openrouter"] = "sk-or"
    app.models("openrouter")                                    # the panel listed the models first
    added = app.add_brain("openrouter", ULTRA[0])
    assert "busy" in added["warning"] and added["native_tools"] is True
    assert app.config.brain.model == ULTRA[0]


def test_openrouter_privacy_setting_problem_is_explained(home):
    app, _ = make_app(("POST", "/chat/completions", response(
        {"error": {"message": "No endpoints found matching your data policy (Free model publication)"}}, 404)))
    app.config.keys["openrouter"] = "sk-or"
    with pytest.raises(PanelError, match="settings/privacy"):
        app.add_brain("openrouter", ULTRA[0])
    failure = app.runtime.audit.recent()[-1]
    assert failure["event"] == "brain_add_failed" and failure["model"] == ULTRA[0]


# ---------- specialists ----------
def test_specialists_are_chosen_in_the_panel(home):
    app, _ = make_app()
    app.set_specialist("image", "pollinations", "")
    app.set_specialist("writer", "openrouter", "cohere/north-mini-code:free")
    assert cfg.load().media["image"]["provider"] == "pollinations"
    state = app.state()["specialists"]
    assert state["image"]["provider"] == "pollinations" and state["writer"]["model"] == "cohere/north-mini-code:free"
    assert "pollinations" in [s["id"] for s in state["services"]["image"]]
    with pytest.raises(PanelError):
        app.set_specialist("image", "no-such-service", "")
    with pytest.raises(PanelError):
        app.set_specialist("video", "pollinations", "")
    app.set_specialist("image", "", "")                     # off again
    assert not app.runtime.studio.ready("image")


def test_a_pollinations_key_is_optional_and_kept_like_the_other_keys(home):
    app, _ = make_app()
    app.save_service_key("pollinations", " pk_free_key_123 ")
    assert app.config.keys["pollinations"] == "pk_free_key_123"
    assert app.state()["specialists"]["pollinations_key"] == "pk_f…_123"
    app.save_service_key("pollinations", "")
    assert "pollinations" not in app.config.keys


def test_a_pasted_openrouter_key_is_really_checked(home):
    # OpenRouter's model list answers any key, so the key itself is checked
    app, web = make_app(("GET", "openrouter.ai/api/v1/key", response({"error": "No auth credentials found"}, 401)),
                        free_catalog(ULTRA))
    with pytest.raises(PanelError, match="rejected"):
        app.save_key("openrouter", "sk-or-v1-typo")
    assert "openrouter" not in app.config.keys
    assert web.requests[0][1] == "https://openrouter.ai/api/v1/key"
