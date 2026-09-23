"""v0.2 tests: seeded RNG, watch-mode event stream, compare fairness, stops.

Every test here pins down the v0.2 contracts: determinism (same seed ->
identical streams and identical sim results), the JSON-serializable event
stream, provably-shared dice in compare mode, and stop-loss / stop-win /
ruin end reasons.
"""
import json

import pytest

from portroyale.cli import main as cli_main
from portroyale.games.craps import CrapsTable
from portroyale.sim import (
    SimConfig,
    make_dice_stream,
    run_comparison,
    run_session,
    run_simulation,
    watch_session,
)


# ------------------------------------------------------------- seeded engine
def test_table_seed_makes_dice_deterministic():
    a = CrapsTable(seed=123)
    b = CrapsTable(seed=123)
    assert [a.roll().total for _ in range(30)] == [
        b.roll().total for _ in range(30)
    ]


def test_table_different_seeds_differ():
    assert make_dice_stream(1, 50) != make_dice_stream(2, 50)


def test_make_dice_stream_stable():
    assert make_dice_stream(7, 100) == make_dice_stream(7, 100)


def test_session_seed_derives_from_master():
    cfg = SimConfig(strategy="passline_odds", bankroll=1000.0, rolls=50,
                    sessions=4, seed=7, workers=1).as_dict()
    assert run_session(cfg, 0).seed == 7
    assert run_session(cfg, 3).seed == 10


# ------------------------------------------------------- watch-mode stream
def test_same_seed_identical_event_streams():
    a = list(watch_session(seed=42, rolls=100))
    b = list(watch_session(seed=42, rolls=100))
    assert a == b
    assert a[0]["type"] == "session_start"
    assert a[-1]["type"] == "session_end"


def test_different_seeds_differ():
    a = list(watch_session(seed=42, rolls=100))
    b = list(watch_session(seed=43, rolls=100))
    assert a != b


def test_every_event_json_serializable():
    for strategy in ("passline_odds", "dontpass_odds", "ironcross", "presser"):
        events = list(watch_session(strategy=strategy, seed=99, rolls=200))
        assert len(events) > 200  # more than one event per roll on average
        for ev in events:
            json.dumps(ev)  # must not raise
        types = {ev["type"] for ev in events}
        assert {"session_start", "roll", "bankroll",
                "session_end"} <= types


def test_roll_events_carry_dice_and_state():
    events = list(watch_session(seed=42, rolls=10))
    rolls = [ev for ev in events if ev["type"] == "roll"]
    assert len(rolls) == 10
    for ev in rolls:
        assert 1 <= ev["d1"] <= 6 and 1 <= ev["d2"] <= 6
        assert ev["total"] == ev["d1"] + ev["d2"]
        assert ev["phase"] in ("comeout", "point")


def test_bet_placed_and_resolved_events_line_up():
    events = list(watch_session(strategy="passline_odds", seed=42, rolls=30))
    placed = [ev for ev in events if ev["type"] == "bet_placed"]
    resolved = [ev for ev in events if ev["type"] == "bet_resolved"]
    assert placed, "expected some bets to be placed"
    assert resolved, "expected some bets to resolve"
    for ev in resolved:
        assert ev["outcome"] in ("won", "lost", "push", "returned", "travel")


def test_same_seed_identical_sim_results():
    kw = dict(strategy="passline_odds", bankroll=1000.0, rolls=500,
              sessions=8, seed=42, workers=1)
    r1 = run_simulation(SimConfig(**kw))
    r2 = run_simulation(SimConfig(**kw))
    assert r1.realized_edge == r2.realized_edge
    assert r1.median_final == r2.median_final
    assert r1.mean_final == r2.mean_final
    assert r1.end_reasons == r2.end_reasons


# ------------------------------------------------------------- stop control
def test_stop_loss_triggers():
    dice = [(1, 1)] * 300  # every come-out is craps: pass line bleeds $10/roll
    events = list(watch_session(strategy="passline_odds", seed=1,
                                bankroll=1000.0, rolls=300,
                                stop_loss=0.5, dice=dice))
    end = events[-1]
    assert end["type"] == "session_end"
    assert end["reason"] == "stop_loss"
    assert end["rolls_played"] == 50
    assert end["final_bankroll"] == pytest.approx(500.0)


def test_stop_win_triggers():
    dice = [(3, 4)] * 300  # every come-out is a natural: pass line wins $10/roll
    events = list(watch_session(strategy="passline_odds", seed=1,
                                bankroll=1000.0, rolls=300,
                                stop_win=1.5, dice=dice))
    end = events[-1]
    assert end["type"] == "session_end"
    assert end["reason"] == "stop_win"
    assert end["rolls_played"] == 50
    assert end["final_bankroll"] == pytest.approx(1500.0)


def test_ruin_end_reason():
    dice = [(1, 1)] * 500
    events = list(watch_session(strategy="passline_odds", seed=3,
                                bankroll=20.0, rolls=500, dice=dice))
    end = events[-1]
    assert end["reason"] == "ruin"
    assert end["final_bankroll"] < 5.0


def test_rolls_exhausted_end_reason():
    events = list(watch_session(seed=5, rolls=30))
    end = events[-1]
    assert end["reason"] == "rolls_exhausted"
    assert end["rolls_played"] == 30


def test_end_reasons_reported_in_sim_stats():
    config = SimConfig(strategy="passline_odds", bankroll=1000.0, rolls=200,
                       sessions=6, seed=11, stop_loss=0.5, workers=1)
    report = run_simulation(config)
    assert abs(sum(report.end_reasons.values()) - 1.0) < 1e-9
    assert set(report.end_reasons) <= {
        "rolls_exhausted", "ruin", "stop_loss", "stop_win", "error"}


def test_bad_stop_values_rejected():
    with pytest.raises(ValueError):
        SimConfig(stop_loss=0)
    with pytest.raises(ValueError):
        watch_session(stop_win=-1.0)


# ------------------------------------------------------- compare / fairness
def test_compare_strategies_see_identical_dice():
    """Common random numbers: same fixed dice -> same dice in both streams."""
    dice = make_dice_stream(7, 200)
    streams = {}
    for name in ("passline_odds", "ironcross"):
        rolls = [ev for ev in watch_session(strategy=name, seed=7, rolls=200,
                                            dice=dice) if ev["type"] == "roll"]
        streams[name] = [(ev["d1"], ev["d2"]) for ev in rolls]
    n = min(len(streams["passline_odds"]), len(streams["ironcross"]))
    assert n > 50, "sessions ended too early for a meaningful check"
    assert streams["passline_odds"][:n] == streams["ironcross"][:n] == dice[:n]


def test_compare_requires_seed():
    with pytest.raises(ValueError, match="requires a seed"):
        run_comparison(strategies=["passline_odds", "ironcross"],
                       seed=None, sessions=2, rolls=50, workers=1)


def test_compare_needs_two_strategies():
    with pytest.raises(ValueError, match="at least two"):
        run_comparison(strategies=["passline_odds"], seed=7,
                       sessions=2, rolls=50, workers=1)


def test_compare_report_sane():
    report = run_comparison(
        strategies=["passline_odds", "ironcross"],
        bankroll=1000.0, rolls=500, sessions=6, seed=7, workers=1)
    assert set(report.reports) == {"passline_odds", "ironcross"}
    for name, rep in report.reports.items():
        assert rep.sessions == 6
        assert 0.0 <= rep.win_rate <= 1.0
        assert abs(sum(rep.end_reasons.values()) - 1.0) < 1e-9
    rows = report.table_rows()
    assert [r["strategy"] for r in rows] == ["passline_odds", "ironcross"]


# ------------------------------------------------------------------------ CLI
def test_cli_watch_runs(capsys):
    assert cli_main(["watch", "--rolls", "10", "--seed", "1"]) == 0
    out = capsys.readouterr().out
    assert "Watching craps / passline_odds" in out
    assert "session over" in out


def test_cli_compare_runs(capsys):
    rc = cli_main(["compare", "--strategies", "passline_odds,ironcross",
                   "--sessions", "4", "--rolls", "200", "--seed", "7",
                   "--workers", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Identical dice for every strategy" in out
    assert "passline_odds" in out and "ironcross" in out


def test_cli_compare_without_seed_fails(capsys):
    assert cli_main(["compare", "--strategies",
                     "passline_odds,ironcross"]) == 2
    assert "requires a seed" in capsys.readouterr().err
