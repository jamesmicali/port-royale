"""Rule-correctness tests for the craps engine.

Every test drives the table with *fixed dice* (``table.roll(d1, d2)``) so
the assertions are exact, not statistical.
"""
import pytest

from portroyale.games.base import InsufficientBankroll, TableLimitError
from portroyale.games.craps import CrapsTable


def make_table(**kwargs):
    defaults = dict(bankroll=1000.0, min_bet=5.0, max_bet=5000.0, odds_multiple=5)
    defaults.update(kwargs)
    return CrapsTable(**defaults)


# ------------------------------------------------------------------ come-out
def test_comeout_natural_wins_pass():
    t = make_table()
    t.place_bet("pass", 10)
    t.roll(3, 4)  # 7
    assert t.bankroll == pytest.approx(1010.0)
    assert t.phase == "comeout" and t.point is None


def test_comeout_eleven_wins_pass():
    t = make_table()
    t.place_bet("pass", 10)
    t.roll(5, 6)  # 11
    assert t.bankroll == pytest.approx(1010.0)


def test_comeout_craps_loses_pass():
    for dice in [(1, 1), (1, 2), (6, 6)]:  # 2, 3, 12
        t = make_table()
        t.place_bet("pass", 10)
        t.roll(*dice)
        assert t.bankroll == pytest.approx(990.0), dice


def test_dontpass_wins_on_craps():
    t = make_table()
    t.place_bet("dontpass", 10)
    t.roll(1, 1)  # 2
    assert t.bankroll == pytest.approx(1010.0)


def test_dontpass_pushes_on_twelve():
    t = make_table()
    t.place_bet("dontpass", 10)
    t.roll(6, 6)  # 12 -> bar, push
    assert t.bankroll == pytest.approx(1000.0)
    assert not t.has_bet("dontpass")


def test_dontpass_loses_on_seven():
    t = make_table()
    t.place_bet("dontpass", 10)
    t.roll(3, 4)  # 7
    assert t.bankroll == pytest.approx(990.0)


# --------------------------------------------------------------------- point
def test_point_established_then_made():
    t = make_table()
    t.place_bet("pass", 10)
    t.roll(2, 4)  # 6 -> point
    assert t.phase == "point" and t.point == 6
    t.roll(1, 1)  # 2: nothing happens
    assert t.bankroll == pytest.approx(990.0)
    t.roll(3, 3)  # 6: point made, pass wins
    assert t.bankroll == pytest.approx(1010.0)
    assert t.phase == "comeout" and t.point is None


def test_seven_out():
    t = make_table()
    t.place_bet("pass", 10)
    t.place_bet("dontpass", 10)
    t.roll(2, 4)  # point 6
    t.roll(4, 3)  # 7: seven-out
    # pass lost 10, don't pass won 10 -> back to 1000
    assert t.bankroll == pytest.approx(1000.0)
    assert t.phase == "comeout" and t.point is None
    assert t.shooter_rolls == 0  # new shooter


# ---------------------------------------------------------------------- odds
@pytest.mark.parametrize(
    "point_dice,odds,expected_profit",
    [((1, 3), 10, 30.0),   # point 4: 10 flat wins 10 + 10 odds @2:1 wins 20
     ((2, 3), 10, 25.0),   # point 5: 10 + 10 @3:2 wins 15
     ((1, 5), 10, 22.0)],  # point 6: 10 + 10 @6:5 wins 12
)
def test_pass_odds_true_odds(point_dice, odds, expected_profit):
    t = make_table()
    t.place_bet("pass", 10)
    t.roll(*point_dice)
    t.add_odds("pass", odds)
    start = t.bankroll
    t.roll(*point_dice)  # point made: flat 10 wins 10, odds win odds*mult
    assert t.bankroll == pytest.approx(start + 20 + expected_profit)


def test_pass_odds_lost_on_seven_out():
    t = make_table()
    t.place_bet("pass", 10)
    t.roll(1, 3)  # point 4
    t.add_odds("pass", 10)
    t.roll(3, 4)  # 7
    assert t.bankroll == pytest.approx(980.0)  # lost flat 10 + odds 10


def test_dontpass_lay_odds():
    t = make_table()
    t.place_bet("dontpass", 10)
    t.roll(1, 3)  # point 4
    t.add_odds("dontpass", 20)  # lay 20 to win 10
    t.roll(3, 4)  # 7: don't wins flat 10 + lay 10
    assert t.bankroll == pytest.approx(1020.0)


def test_odds_multiple_enforced():
    t = make_table(odds_multiple=3)
    t.place_bet("pass", 10)
    t.roll(1, 5)  # point 6
    with pytest.raises(TableLimitError):
        t.add_odds("pass", 31)  # 3x = 30 max
    t.add_odds("pass", 30)  # exactly 3x is fine


def test_no_duplicate_odds_across_point_rolls():
    """Regression test: odds bets store the point number, so a naive
    ``has_bet("pass_odds")`` lookup (number=None) never matched and
    strategies piled on fresh odds every roll. ``has_odds`` fixes it."""
    t = make_table()
    t.place_bet("pass", 10)
    t.roll(1, 5)  # point 6
    for _ in range(5):
        if t.has_bet("pass") and not t.has_odds("pass"):
            t.add_odds("pass", 50)
        t.roll(2, 3)  # 5: point stays on
    odds = [b for b in t.bets if b.kind == "pass_odds"]
    assert len(odds) == 1
    assert t.phase == "point" and t.point == 6


# ---------------------------------------------------------------- place/buy
@pytest.mark.parametrize(
    "number,amount,expected_win",
    [(6, 12, 14.0),   # 7:6
     (8, 12, 14.0),
     (5, 10, 14.0),   # 7:5
     (9, 10, 14.0),
     (4, 10, 18.0),   # 9:5
     (10, 10, 18.0)],
)
def test_place_bet_payouts(number, amount, expected_win):
    t = make_table()
    t.place_bet("pass", 5)
    # Establish a point that ISN'T the number under test, so the winning
    # roll doesn't also make the point and pay the pass line.
    point_dice = (2, 6) if number == 6 else (2, 4)
    t.roll(*point_dice)
    t.place_bet("place", amount, number)
    start = t.bankroll
    d = {4: (1, 3), 5: (2, 3), 6: (1, 5), 8: (2, 6), 9: (3, 6), 10: (4, 6)}[number]
    t.roll(*d)
    assert t.bankroll == pytest.approx(start + amount + expected_win)


def test_place_bet_loses_on_seven():
    t = make_table()
    t.place_bet("pass", 5)
    t.roll(2, 4)
    t.place_bet("place", 12, 8)
    t.roll(3, 4)  # 7
    assert t.bankroll == pytest.approx(983.0)


def test_buy_bet_pays_true_odds_less_commission():
    t = make_table()
    t.place_bet("pass", 5)
    t.roll(1, 3)  # point 4
    t.place_bet("buy", 20, 4)
    t.roll(2, 2)  # hard 4: point made (pass +10) and buy wins 20 @2:1 - 5% = +38
    assert t.bankroll == pytest.approx(1043.0)


# ------------------------------------------------------------------ one-roll
def test_field_pays_double_on_2_and_12():
    for dice in [(1, 1), (6, 6)]:
        t = make_table()
        t.place_bet("field", 10)
        t.roll(*dice)
        assert t.bankroll == pytest.approx(1020.0), dice


def test_field_loses_on_5():
    t = make_table()
    t.place_bet("field", 10)
    t.roll(2, 3)
    assert t.bankroll == pytest.approx(990.0)


def test_hardways():
    t = make_table()
    t.place_bet("pass", 5)
    t.roll(2, 4)  # point 6
    t.place_bet("hard", 5, 8)
    t.roll(4, 4)  # hard 8 -> 9:1
    assert t.bankroll == pytest.approx(1000 - 5 - 5 + 5 + 45)


def test_hardway_loses_on_easy():
    t = make_table()
    t.place_bet("pass", 5)
    t.roll(2, 4)
    t.place_bet("hard", 5, 8)
    t.roll(5, 3)  # easy 8
    assert t.bankroll == pytest.approx(1000 - 5 - 5)


def test_any_seven_prop():
    t = make_table()
    t.place_bet("any_seven", 5)
    t.roll(3, 4)
    assert t.bankroll == pytest.approx(1000 + 20)  # 4:1


# ------------------------------------------------------------------ come bets
def test_come_bet_travels_then_wins():
    t = make_table()
    t.place_bet("pass", 10)
    t.roll(2, 4)  # point 6
    t.place_bet("come", 10)  # in transit
    t.roll(2, 6)  # 8: come travels to 8
    assert t.has_bet("come", 8)
    t.roll(4, 4)  # 8: come wins
    assert t.bankroll == pytest.approx(1000 - 10 - 10 + 20)


def test_come_bet_wins_on_seven_while_in_transit():
    t = make_table()
    t.place_bet("pass", 10)
    t.roll(2, 4)  # point 6
    t.place_bet("come", 10)
    t.roll(3, 4)  # 7: seven-out for the pass line, but the in-transit come wins
    outcomes = [(e.kind, e.outcome) for e in t.drain_events()]
    assert ("pass", "lost") in outcomes
    assert ("come", "won") in outcomes
    assert t.bankroll == pytest.approx(1000.0)  # -10 pass, +20 come
