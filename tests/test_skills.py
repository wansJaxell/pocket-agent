from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pocketagent.memory import NoteStore, ReminderStore
from pocketagent.skills.basics import calculate, get_current_time
from pocketagent.skills.files import list_files, read_file, write_file
from pocketagent.skills.notes import forget, recall, remember
from pocketagent.skills.reminders import parse_when, set_reminder
from pocketagent.skills.web import fetch_webpage, html_to_text, parse_search_results, web_search
from pocketagent.tools import ToolContext


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(workspace=tmp_path / "ws", memory=NoteStore(tmp_path / "mem"),
                       reminders=ReminderStore(tmp_path / "mem"), chat_id="42")


# ---------- calculator ----------
@pytest.mark.parametrize("expression, expected", [
    ("(1250 * 0.18) + 40", "265"), ("2^10", "1024"), ("sqrt(16) + pi * 0", "4"), ("7 // 2", "3")])
def test_calculate(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("attack", ["__import__('os').system('dir')", "open('x').read()", "9**9**9**9"])
def test_calculator_refuses_code_and_huge_numbers(attack):
    assert calculate(attack).startswith("Cannot calculate")


def test_time_with_and_without_timezone():
    assert "2" in get_current_time()
    assert "Unknown time zone" in get_current_time("Mars/Olympus")


# ---------- files: sandbox ----------
def test_write_read_and_list(ctx):
    assert "Saved" in write_file(ctx, "reports/plan.md", "Hello")
    write_file(ctx, "reports/plan.md", " world", append=True)
    assert read_file(ctx, "reports/plan.md") == "Hello world"
    assert "[dir] reports" in list_files(ctx)


@pytest.mark.parametrize("escape", ["../secret.txt", "../../Windows/win.ini", "/etc/passwd"])
def test_files_cannot_leave_the_workspace(ctx, escape):
    with pytest.raises(PermissionError):
        read_file(ctx, escape)


# ---------- notes ----------
def test_remember_recall_forget(ctx):
    remember(ctx, "The user's daughter is called Elif")
    remember(ctx, "The user works in a foundry")
    assert "Elif" in recall(ctx, "daughter")
    assert "foundry" not in recall(ctx, "daughter")
    assert forget(ctx, 1) == "Note #1 deleted."
    assert "Elif" not in recall(ctx)


# ---------- reminders ----------
NOW = datetime(2026, 10, 24, 18, 0)


@pytest.mark.parametrize("when, expected", [
    ("in 10 minutes", datetime(2026, 10, 24, 18, 10)),
    ("in 2 hours", datetime(2026, 10, 24, 20, 0)),
    ("18:30", datetime(2026, 10, 24, 18, 30)),
    ("09:00", datetime(2026, 10, 25, 9, 0)),          # already passed today -> tomorrow
    ("2026-11-01 08:15", datetime(2026, 11, 1, 8, 15)),
])
def test_parse_when(when, expected):
    assert parse_when(when, now=NOW) == expected


def test_bad_time_is_explained():
    with pytest.raises(ValueError, match="cannot understand"):
        parse_when("when the cows come home", now=NOW)


def test_reminder_is_stored_and_popped_when_due(ctx):
    assert "Reminder #1 set" in set_reminder(ctx, "in 5 minutes", "call mum")
    store = ctx.reminders
    assert store.pop_due(now=datetime.now()) == []
    due = store.pop_due(now=datetime(2100, 1, 1))
    assert due[0]["text"] == "call mum" and due[0]["chat_id"] == "42"
    assert store.all() == []


# ---------- web ----------
def test_html_to_text_drops_scripts_and_styles():
    page = "<html><head><title>x</title><style>p{}</style></head><body><h1>News</h1>" \
           "<script>evil()</script><p>Hello <b>world</b></p></body></html>"
    text = html_to_text(page)
    assert text.splitlines() == ["News", "Hello world"]
    assert "evil" not in text and "p{}" not in text


def test_fetch_only_allows_http():
    assert "Only http" in fetch_webpage("file:///C:/Windows/win.ini")


SEARCH_PAGE = """
<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=1">First &amp; best</a>
<a class="result__snippet" href="x">Snippet <b>one</b></a></div>
<div class="result"><a rel="nofollow" class="result__a" href="https://example.org/b">Second</a>
<a class="result__snippet" href="y">Snippet two</a></div>"""


def test_parse_search_results_unwraps_redirect_links():
    results = parse_search_results(SEARCH_PAGE)
    assert results[0] == {"title": "First & best", "url": "https://example.com/a", "snippet": "Snippet one"}
    assert results[1]["url"] == "https://example.org/b"


def test_web_search_uses_parsed_results():
    with patch("pocketagent.skills.web.requests.post", return_value=Mock(text=SEARCH_PAGE, raise_for_status=Mock())):
        assert "https://example.com/a" in web_search("anything")
