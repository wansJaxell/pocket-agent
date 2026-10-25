"""Specialists chosen automatically from what is connected, and voices in the language of the answer."""

from types import SimpleNamespace

import pytest
from conftest import FakeWeb, response

from pocketagent import media
from pocketagent.app import App
from pocketagent.config import BrainConfig, Config
from pocketagent.llm import PROVIDERS
from pocketagent.media import Studio, guess_language, voice_path


@pytest.mark.parametrize("text, language", [
    ("Yarın İstanbul'da hava güneşli olacak, sıcaklık 18 derece.", "tr"),
    ("Tomorrow the weather in London will be sunny and warm.", "en"),
    ("Morgen wird das Wetter in Berlin sonnig und warm, und nicht kalt.", "de"),
    ("Demain, le temps sera ensoleillé à Paris et il fera chaud.", "fr"),
    ("Mañana el tiempo en Madrid será soleado y hará calor.", "es"),
    ("Завтра в Москве будет солнечно и тепло.", "ru"),
    ("Завтра у Києві буде сонячно і тепло, їжте морозиво.", "uk"),
    ("غدا سيكون الطقس مشمسا في عمان", "ar"),
    ("明天北京天气晴朗", "zh"),
    # short English answers: "a", "o", "I" must not make them Portuguese or Polish
    ("Sure! I set a reminder for 8 o'clock tomorrow.", "en"),
    ("I found a cheaper flight at 9 a.m. on Pegasus.", "en"),
    ("Here's what I can do: read your files, set reminders and search the web.", "en"),
    ("My name is Pocket. How can I help?", "en"),
    ("Encontrei um voo mais barato para você amanhã.", "pt"),
    ("Mam nadzieję, że to jest dobre.", "pl"),
])
def test_the_language_of_an_answer_is_recognised(text, language):
    assert guess_language(text) == language


def test_voice_download_paths():
    assert voice_path("tr_TR-dfki-medium") == "tr/tr_TR/dfki/medium/tr_TR-dfki-medium"
    assert voice_path("uk_UA-ukrainian_tts-medium") == "uk/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium"
    assert {"tr_TR-dfki-medium", "en_US-amy-medium", "de_DE-thorsten-medium", "ar_JO-kareem-medium"} <= set(media.PIPER_VOICES)


def install_voices(home, *voices):
    (home / "piper" / "piper").mkdir(parents=True)
    (home / "piper" / "piper" / "piper.exe").write_bytes(b"MZ")
    (home / "piper" / "voices").mkdir()
    for voice in voices:
        (home / "piper" / "voices" / f"{voice}.onnx").write_bytes(b"onnx")


def piper_runner(runs):
    def run(argv, input, **kwargs):
        runs.append(argv[argv.index("--model") + 1])
        with open(argv[argv.index("--output_file") + 1], "wb") as f:
            f.write(b"RIFF")
        return SimpleNamespace(returncode=0, stderr=b"")
    return run


def test_piper_speaks_each_answer_in_its_own_language(home, monkeypatch):
    monkeypatch.setattr(media.os, "name", "nt")
    install_voices(home, "tr_TR-dfki-medium", "en_US-amy-medium")
    config, runs = Config(), []
    config.media["speech"] = {"provider": "piper", "voice": "auto", "model": ""}
    studio = Studio(config, run=piper_runner(runs))
    studio.speech("Merhaba, bugün hava çok güzel.")
    studio.speech("Hello, the weather is lovely today.")
    studio.speech("Guten Tag, das Wetter ist heute schön und nicht kalt.")      # no German voice: the default
    assert [r.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for r in runs] == [
        "tr_TR-dfki-medium.onnx", "en_US-amy-medium.onnx", "en_US-amy-medium.onnx"]


def test_windows_voices_are_chosen_by_language_too(monkeypatch):
    monkeypatch.setattr(media.os, "name", "nt")
    seen = []

    def sapi(argv, env, **kwargs):
        seen.append(env.get("PA_CULTURE"))
        with open(env["PA_OUT"], "wb") as f:
            f.write(b"RIFF")
        return SimpleNamespace(returncode=0, stderr="")
    config = Config()
    config.media["speech"] = {"provider": "local", "voice": "", "model": ""}
    Studio(config, run=sapi).speech("Bonjour, il fait beau aujourd'hui et le ciel est bleu.")
    assert seen == ["fr-FR"]


# ---------- automatic choices ----------
def connected(*brains, keys=None, off=()):
    config = Config()
    config.set_brains(list(brains))
    config.keys = keys if keys is not None else {"nvidia": "n", "groq": "g", "gemini": "m"}
    config.disabled_providers = list(off)
    return config


NVIDIA = BrainConfig("nvidia", PROVIDERS["nvidia"].base_url, "nvidia/nemotron-3-ultra-550b-a55b")
GROQ = BrainConfig("groq", PROVIDERS["groq"].base_url, "openai/gpt-oss-120b")
GEMINI = BrainConfig("gemini", PROVIDERS["gemini"].base_url, "gemini-3.5-flash")


def test_hearing_uses_groq_whisper_when_a_groq_key_is_saved():
    assert Studio(connected(NVIDIA, GROQ)).choice("hearing") == {"provider": "groq", "model": "", "auto": True}
    assert Studio(connected(NVIDIA, keys={"nvidia": "n"})).choice("hearing") == {}
    assert Studio(connected(NVIDIA, GROQ, off=["groq"])).choice("hearing") == {}


def test_seeing_uses_the_first_brain_that_can_see_pictures():
    studio = Studio(connected(NVIDIA, GROQ, GEMINI))
    assert studio.choice("vision") == {"provider": "gemini", "model": "gemini-3.5-flash", "auto": True}
    flagged = BrainConfig("openrouter", PROVIDERS["openrouter"].base_url, "some/new-model:free", sees_images=True)
    assert Studio(connected(flagged, GEMINI, keys={"openrouter": "o", "gemini": "m"})).choice("vision")["model"] == \
        "some/new-model:free"
    off = BrainConfig("gemini", PROVIDERS["gemini"].base_url, "gemini-3.5-flash", enabled=False)
    assert Studio(connected(NVIDIA, off)).choice("vision") == {}


def test_a_choice_made_in_the_panel_wins_over_the_automatic_one():
    config = connected(NVIDIA, GROQ, GEMINI)
    config.media["vision"] = {"provider": "groq", "model": "meta-llama/llama-4-scout-17b-16e-instruct"}
    assert Studio(config).choice("vision")["model"] == "meta-llama/llama-4-scout-17b-16e-instruct"


def test_speech_uses_piper_when_installed_otherwise_the_computers_voice(home, monkeypatch):
    monkeypatch.setattr(media.os, "name", "nt")
    assert Studio(Config()).choice("speech")["provider"] == "local"
    install_voices(home, "tr_TR-dfki-medium")
    assert Studio(Config()).choice("speech") == {"provider": "piper", "model": "", "voice": "auto", "auto": True}


def test_a_photo_is_understood_without_any_setup(home):
    web = FakeWeb(("POST", "/chat/completions", response({"choices": [{"message": {"content": "Bir uçak bileti."}}]})))
    config = connected(NVIDIA, GEMINI)
    studio = Studio(config, http=web)
    assert studio.ready("vision") and studio.look(b"\xff\xd8", "image/jpeg", "Bu ne?") == "Bir uçak bileti."
    assert web.requests[0][2]["json"]["model"] == "gemini-3.5-flash"


def test_the_panel_shows_what_is_used_automatically(home):
    config = connected(NVIDIA, GROQ, GEMINI)
    app = App(config, http=FakeWeb())
    auto = app.state()["specialists"]["auto"]
    assert auto["hearing"] == "groq" and auto["vision"] == "gemini · gemini-3.5-flash" and auto["image"] == ""


def test_adding_a_brain_remembers_when_the_list_says_it_sees_pictures(home):
    web = FakeWeb(("GET", "openrouter.ai/api/v1/models", response({"data": [
        {"id": "nvidia/nemotron-3.5-super-vl:free", "pricing": {"prompt": "0", "completion": "0"},
         "context_length": 1000000, "supported_parameters": ["tools"],
         "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}}]})),
        ("POST", "/chat/completions", response({"choices": [{"message": {"content": "OK"}}]})))
    app = App(Config(), http=web)
    app.config.keys["openrouter"] = "o"
    app.models("openrouter")
    app.add_brain("openrouter", "nvidia/nemotron-3.5-super-vl:free")
    assert app.config.brain.sees_images is True
