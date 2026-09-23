"""End-to-end smoke tests: strategies + Monte Carlo engine."""
import pytest

from portroyale.sim import SimConfig, run_simulation, run_session
from portroyale.strategies import list_strategies, make_strategy


def test_all_strategies_registered():
    names = {s.name for s in list_strategies()}
    assert {"passline_odds", "dontpass_odds", "ironcross", "presser"} <= names


@pytest.mark.parametrize("strategy", ["passline_odds", "dontpass_odds",
                                      "ironcross", "presser"])
def test_strategy_survives_random_rolls(strategy):
    """Every shipped strategy plays 300 random rolls without raising."""
    cfg = SimConfig(strategy=strategy, bankroll=1000.0, rolls=300,
                    sessions=1, seed=7, workers=1).as_dict()
    result = run_session(cfg, 0)
    assert result.rolls_played > 0
    assert result.action > 0


def test_simulation_report_sane():
    config = SimConfig(strategy="passline_odds", bankroll=1000.0,
                       rolls=500, sessions=8, seed=42, workers=1)
    report = run_simulation(config)
    assert report.sessions == 8
    assert 0.0 <= report.win_rate <= 1.0
    assert 0.0 <= report.ruin_rate <= 1.0
    assert report.total_action > 0
    # Pass line + odds is a negative-expectation game: the realized edge
    # should be positive (house wins) within generous noise bounds.
    assert -0.5 < report.realized_edge < 0.5
    for band in ("p5", "p25", "p50", "p75", "p95"):
        assert len(report.bands[band]) == 401
    assert report.bands["p5"][0] == pytest.approx(1000.0)


def test_unknown_strategy_rejected():
    with pytest.raises(ValueError):
        make_strategy("martingale_to_the_moon")


def test_strategy_rejects_bad_param():
    with pytest.raises(ValueError):
        make_strategy("passline_odds", not_a_param=1)
