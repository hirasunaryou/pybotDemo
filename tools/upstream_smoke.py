"""Smoke test against an unmodified, pinned real PyBot installation.

Unlike tests/test_lab.py (which uses an isolated mini fixture), this script
verifies the real upstream bot.runtime.turn() and real trace integration.
"""
from demo.bootstrap import ensure_upstream
from demo.engine import Engine


def main():
    source = ensure_upstream()
    engine = Engine(source)
    session = "upstream_smoke_session"
    first = engine.ask(session, "Hi, I'm Sam.")
    assert first["candidate_count"] >= 1, first
    assert first["module"], first
    assert first["chosen_index"] >= 0, first
    assert first["candidates"][first["chosen_index"]]["module"] == first["module"]
    assert engine.entry_line(first["module"]) >= 1
    print("Real reply:", first["reply"])
    print("Selected:", first["module"], "/ candidates:", first["candidate_count"])
    follow = engine.ask(session, "What's my name?")
    assert follow["candidate_count"] >= 1, follow
    print("Follow-up reply:", follow["reply"])
    details = engine.trace(session, 0, first["module"])
    module_path = "bot/modules/" + first["module"] + ".py"
    assert module_path in details["hits"], details
    assert details["calls"], details
    assert len(engine.session(session).turns) == 2, "Replay changed real conversation"
    print("Trace:", len(details["hits"][module_path]), "lines,", len(details["calls"]), "functions")
    print("Replay matches original:", details["replay_equal"])
    print("Smoke: PASS")


if __name__ == "__main__":
    main()
