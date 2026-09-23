"""Example craps strategies.

Each one is a complete, working strategy you can copy and adapt. They are
deliberately written in plain, readable style — this is the file to study
when you write your own.
"""
from __future__ import annotations

from ..games.craps import LAY_PAY
from .base import Strategy


class PassLineWithOdds(Strategy):
    """The textbook low-edge play: pass line on every come-out, backed with
    the maximum odds the table allows once a point is set."""

    name = "passline_odds"
    description = "Pass line every come-out + max odds behind it."
    PARAMS = {
        "base_unit": {
            "type": "float", "default": 10.0,
            "label": "Base unit ($)", "help": "Pass line bet on each come-out.",
        },
        "odds_multiple": {
            "type": "int", "default": 5,
            "label": "Odds multiple",
            "help": "How many x the flat bet to lay in odds (capped by bankroll).",
        },
    }

    def decide(self, table) -> None:
        if table.phase == "comeout":
            if not table.has_bet("pass") and table.bankroll >= self.base_unit:
                table.place_bet("pass", self.base_unit)
        else:  # point is on: load the odds behind our pass line bet
            if table.has_bet("pass") and not table.has_odds("pass"):
                want = self.base_unit * self.odds_multiple
                amount = min(want, table.bankroll)
                if amount >= table.min_bet:
                    table.add_odds("pass", amount)


class DontPassWithOdds(Strategy):
    """The dark side: don't pass on every come-out, then lay the maximum
    odds. Slightly lower edge than the pass line, and you win when the
    shooter sevens out."""

    name = "dontpass_odds"
    description = "Don't pass every come-out + max lay odds."
    PARAMS = {
        "base_unit": {
            "type": "float", "default": 10.0,
            "label": "Base unit ($)", "help": "Don't pass bet on each come-out.",
        },
        "odds_multiple": {
            "type": "int", "default": 5,
            "label": "Odds multiple",
            "help": "Win-multiple of the flat bet to lay in odds.",
        },
    }

    def decide(self, table) -> None:
        if table.phase == "comeout":
            if not table.has_bet("dontpass") and table.bankroll >= self.base_unit:
                table.place_bet("dontpass", self.base_unit)
        else:
            if table.has_bet("dontpass") and not table.has_odds("dontpass"):
                # Lay enough to *win* `odds_multiple` x the flat bet.
                flat = table.find_bet("dontpass").amount
                cap = self.odds_multiple * flat / LAY_PAY[table.point]
                amount = min(cap, table.bankroll)
                if amount >= table.min_bet:
                    table.add_odds("dontpass", amount)


class IronCross(Strategy):
    """The classic "can't lose" field system: pass line on the come-out,
    then field + place 5/6/8 once the point is set, so every roll except 7
    pays something. Note the branching — we skip placing the point number
    itself, since the pass line already covers it."""

    name = "ironcross"
    description = "Pass line + field + place 5/6/8 after the come-out."
    PARAMS = {
        "base_unit": {
            "type": "float", "default": 10.0,
            "label": "Base unit ($)", "help": "Pass line and field bet size.",
        },
        "place_unit": {
            "type": "float", "default": 12.0,
            "label": "Place bet unit ($)", "help": "Size of each place 5/6/8 bet.",
        },
    }

    def decide(self, table) -> None:
        if table.phase == "comeout":
            if not table.has_bet("pass") and table.bankroll >= self.base_unit:
                table.place_bet("pass", self.base_unit)
            return
        # Point is on: cover everything but the 7.
        if not table.has_bet("field") and table.bankroll >= self.base_unit:
            table.place_bet("field", self.base_unit)
        for n in (5, 6, 8):
            if n == table.point:
                continue  # branch: pass line already covers the point number
            if not table.has_bet("place", n) and table.bankroll >= self.place_unit:
                table.place_bet("place", self.place_unit, n)


class PressAfterWins(Strategy):
    """A stateful strategy: flat pass line with odds, but after two
    *consecutive* winning pass-line bets the base unit doubles (a press);
    any loss resets it. Demonstrates strategy memory via
    ``table.drain_events()`` and ``on_session_start``."""

    name = "presser"
    description = "Pass line + odds; double the unit after two straight wins."
    PARAMS = {
        "base_unit": {
            "type": "float", "default": 10.0,
            "label": "Base unit ($)", "help": "Starting pass line bet.",
        },
        "odds_multiple": {
            "type": "int", "default": 3,
            "label": "Odds multiple", "help": "Odds behind the pass line.",
        },
        "press_after": {
            "type": "int", "default": 2,
            "label": "Press after N wins",
            "help": "Consecutive pass-line wins before doubling the unit.",
        },
    }

    def on_session_start(self, table) -> None:
        self.unit = self.base_unit
        self.streak = 0

    def decide(self, table) -> None:
        # Memory: what happened to our pass line bets since last roll?
        for event in table.drain_events():
            if event.kind == "pass":
                if event.outcome == "won":
                    self.streak += 1
                    if self.streak >= self.press_after:
                        self.unit = self.base_unit * 2  # press!
                elif event.outcome == "lost":
                    self.streak = 0
                    self.unit = self.base_unit  # reset

        if table.phase == "comeout":
            if not table.has_bet("pass") and table.bankroll >= self.unit:
                table.place_bet("pass", self.unit)
        else:
            if table.has_bet("pass") and not table.has_odds("pass"):
                amount = min(self.unit * self.odds_multiple, table.bankroll)
                if amount >= table.min_bet:
                    table.add_odds("pass", amount)
