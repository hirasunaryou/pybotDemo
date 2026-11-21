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

    # This educational example is intentionally source-grounded:
    # the reply appears as the literal _AVERAGE_EXPLAIN in maths.py.
    math_session = "upstream_math_mean"
    math_turn = engine.ask(math_session, "Do you know how to calculate mean?")
    print("Mean demonstration selected:", math_turn["module"])
    print("Mean reply:", math_turn["reply"][:140])
    film = engine.playback(math_session, 0)
    assert film["replay_equal"], film.get("warning")
    assert film["frames"], "Replay film has no real observed frames"
    assert film["frames"][0]["kind"] == "start", film["frames"][0]
    assert any(row["kind"] == "final" for row in film["frames"]), "Missing final answer"
    assert len(film["frames"]) <= film["frame_cap"]
    assert len(engine.session(math_session).turns) == 1, "Replay mutated the live session"
    origin = next((hint for hint in film["source_matches"] if hint["verified_equal"]
                   and hint["path"] == "bot/knowledge/maths.py"), None)
    assert origin is not None, "The exact math reply literal must be found in original source"
    assert origin["symbol"] == "_AVERAGE_EXPLAIN", origin
    assert origin["line"] == 5101, origin
    assert any(x["line"] == 5196 for x in origin["references"]), origin
    print("Mean answer exact source:", origin["path"], "line", origin["line"])
    print("Mean answer static return candidates:", [x["line"] for x in origin["references"]])
    print("Playback:", film["call_count"], "observed calls,", len(film["frames"]),
          "selected display frames; candidate-return matched:", film["candidate_return_matched"])
    print("Smoke: PASS")


if __name__ == "__main__":
    main()
