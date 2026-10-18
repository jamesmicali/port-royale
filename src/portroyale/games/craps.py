"""A correct, fully-featured craps table engine.

The table owns the game state — phase (come-out / point), the point,
bankroll and every live bet — and resolves each roll with true casino
payouts. Strategies observe the table and place/remove bets; the engine
enforces table minimums/maximums, odds multiples and bankroll.

Bet kinds
---------
Line bets:            ``pass``, ``dontpass``
Come bets:            ``come``, ``dontcome`` (``number=None`` while in transit;
                      they travel to a box number on the next roll)
Odds (via add_odds):  ``pass_odds``, ``dontpass_odds``, ``come_odds``,
                      ``dontcome_odds``
Multi-roll:           ``place``, ``buy``, ``lay`` (need ``number``),
                      ``hard`` (needs ``number`` in 4/6/8/10)
One-roll:             ``field``, ``any_seven``, ``any_craps``,
                      ``two_twelve``, ``three_eleven``

House rules modelled
--------------------
- Don't pass / don't come are barred on 12 (push).
- Place / buy / lay / hardway bets are *off* on come-out rolls.
- Pass / don't pass may only be placed on a come-out roll;
  come / don't come only while a point is established.
- Odds pay true odds: 2:1 on 4 & 10, 3:2 on 5 & 9, 6:5 on 6 & 8
  (don't side is the mirror image: 1:2, 2:3, 5:6).
- Place bets pay 9:5 (4/10), 7:5 (5/9), 7:6 (6/8).
- Buy bets pay true odds less 5% commission on the win; lay bets mirror it.
- Field pays 2:1 on 2 and 12, 1:1 on 3/4/9/10/11.
- Hardways pay 7:1 (4/10) and 9:1 (6/8); lose on 7 or the easy way.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import (
    Bet,
    BetEvent,
    RoundResult,
    Table,
    TableLimitError,
    UnknownBetError,
)

POINT_NUMBERS = (4, 5, 6, 8, 9, 10)
HARD_NUMBERS = (4, 6, 8, 10)

# Profit per unit staked.
ODDS_PAY = {4: 2.0, 10: 2.0, 5: 1.5, 9: 1.5, 6: 6 / 5, 8: 6 / 5}
LAY_PAY = {4: 1 / 2, 10: 1 / 2, 5: 2 / 3, 9: 2 / 3, 6: 5 / 6, 8: 5 / 6}
PLACE_PAY = {4: 9 / 5, 10: 9 / 5, 5: 7 / 5, 9: 7 / 5, 6: 7 / 6, 8: 7 / 6}
BUY_PAY = {n: ODDS_PAY[n] * 0.95 for n in ODDS_PAY}   # 5% commission on the win
LAY_BET_PAY = {n: LAY_PAY[n] * 0.95 for n in LAY_PAY}
HARD_PAY = {4: 7.0, 10: 7.0, 6: 9.0, 8: 9.0}
FIELD_PAY = {2: 2.0, 12: 2.0, 3: 1.0, 4: 1.0, 9: 1.0, 10: 1.0, 11: 1.0}
PROP_PAY = {
    "any_seven": 4.0,
    "any_craps": 7.0,
    "two_twelve": 30.0,
    "three_eleven": 15.0,
}
PROP_WINNERS = {
    "any_seven": (7,),
    "any_craps": (2, 3, 12),
    "two_twelve": (2, 12),
    "three_eleven": (3, 11),
}

_ODDS_KINDS = ("pass_odds", "dontpass_odds", "come_odds", "dontcome_odds")
_FLAT_FOR_ODDS = {
    "pass": "pass_odds",
    "dontpass": "dontpass_odds",
    "come": "come_odds",
    "dontcome": "dontcome_odds",
}


@dataclass
class CrapsRollResult(RoundResult):
    d1: int = 0
    d2: int = 0
    total: int = 0
    phase: str = ""
    point: Optional[int] = None


class CrapsTable(Table):
    """A craps table.

    Pass ``seed`` for a per-table ``random.Random`` dice source (a session
    is then fully determined by its seed). ``rng`` is the legacy hook for a
    numpy-style Generator exposing ``.integers(low, high)``.
    """

    def __init__(
        self,
        bankroll: float = 1000.0,
        min_bet: float = 5.0,
        max_bet: float = 5000.0,
        odds_multiple: int = 5,
        seed: Optional[int] = None,
        rng=None,
    ) -> None:
        super().__init__(bankroll=bankroll, seed=seed, rng=rng)
        self.min_bet = float(min_bet)
        self.max_bet = float(max_bet)
        self.odds_multiple = int(odds_multiple)
        self.phase: str = "comeout"   # "comeout" | "point"
        self.point: Optional[int] = None
        self.roll_count = 0
        self.shooter_rolls = 0
        self.last_roll: Optional[tuple[int, int]] = None

    # ------------------------------------------------------------------
    # Placing / removing bets
    # ------------------------------------------------------------------
    def place_bet(self, kind: str, amount: float, number: Optional[int] = None) -> Bet:
        """Place a new bet, deducting it from the bankroll.

        Odds bets are never placed directly — use :meth:`add_odds` so the
        engine can attach them to the right flat bet and enforce the odds
        multiple.
        """
        amount = float(amount)
        self._validate_bet(kind, amount, number)
        self._charge(amount)
        bet = Bet(kind, amount, number)
        self.bets.append(bet)
        return bet

    def _validate_bet(self, kind: str, amount: float, number: Optional[int]) -> None:
        if amount < self.min_bet - 1e-9:
            raise TableLimitError(f"${amount:g} is below the ${self.min_bet:g} minimum")
        if amount > self.max_bet + 1e-9:
            raise TableLimitError(f"${amount:g} is above the ${self.max_bet:g} maximum")

        if kind in ("pass", "dontpass"):
            if number is not None:
                raise TableLimitError(f"{kind} takes no number")
            if self.phase != "comeout":
                raise TableLimitError(f"{kind} can only be bet on a come-out roll")
        elif kind in ("come", "dontcome"):
            if number is not None:
                raise TableLimitError(f"{kind} starts in transit (no number yet)")
            if self.phase != "point":
                raise TableLimitError(f"{kind} can only be bet while a point is on")
        elif kind in _ODDS_KINDS:
            raise TableLimitError(f"use add_odds() to place {kind}")
        elif kind in ("place", "buy", "lay"):
            if number not in POINT_NUMBERS:
                raise TableLimitError(f"{kind} needs a box number {POINT_NUMBERS}")
            if self.phase != "point":
                raise TableLimitError(f"{kind} bets are off on the come-out")
        elif kind == "hard":
            if number not in HARD_NUMBERS:
                raise TableLimitError(f"hardway needs a number in {HARD_NUMBERS}")
        elif kind == "field":
            if number is not None:
                raise TableLimitError("field takes no number")
        elif kind in PROP_PAY:
            if number is not None:
                raise TableLimitError(f"{kind} takes no number")
        else:
            raise UnknownBetError(f"unknown bet kind: {kind!r}")

    def add_odds(self, kind: str, amount: float, number: Optional[int] = None) -> Bet:
        """Add odds behind a flat pass/don't-pass/come/don't-come bet.

        ``kind`` is the *flat* bet kind; for come/don't-come give the box
        ``number`` of the established bet. The odds cap is
        ``odds_multiple`` x the flat bet (measured by *profit* you can win,
        so don't-side caps are converted with the lay ratio).
        """
        if kind not in _FLAT_FOR_ODDS:
            raise UnknownBetError(f"cannot take odds on {kind!r}")
        amount = float(amount)
        flat = self.find_bet(kind, number)
        if flat is None:
            raise TableLimitError(f"no {kind} bet to put odds behind")
        if kind in ("pass", "dontpass") and self.phase != "point":
            raise TableLimitError("odds can only be added while a point is on")

        point_no = self.point if kind in ("pass", "dontpass") else flat.number
        if point_no is None:
            raise TableLimitError("that bet has no number yet (still in transit)")

        if kind in ("pass", "come"):
            cap = self.odds_multiple * flat.amount
        else:  # don't side: the multiple applies to what you can WIN
            cap = self.odds_multiple * flat.amount / LAY_PAY[point_no]
        if amount > cap + 1e-9:
            raise TableLimitError(
                f"${amount:g} odds exceeds {self.odds_multiple}x "
                f"(max ${cap:g} on this bet)"
            )
        if amount < self.min_bet - 1e-9:
            raise TableLimitError(f"${amount:g} is below the ${self.min_bet:g} minimum")

        self._charge(amount)
        odds_kind = _FLAT_FOR_ODDS[kind]
        bet = Bet(odds_kind, amount, point_no)
        self.bets.append(bet)
        return bet

    def take_down(self, kind: str, number: Optional[int] = None) -> Bet:
        """Remove a bet and refund its stake (odds & come bets excepted)."""
        bet = self.find_bet(kind, number)
        if bet is None:
            raise TableLimitError(f"no {kind} bet to take down")
        if kind in _ODDS_KINDS:
            raise TableLimitError("odds can't be taken down while the flat bet lives")
        self._settle(bet, "returned")
        return bet

    def has_odds(self, kind: str, number: Optional[int] = None) -> bool:
        """Is there an odds bet behind flat bet ``kind``?

        ``kind`` is the *flat* bet kind (``"pass"``, ``"dontpass"``,
        ``"come"``, ``"dontcome"``); ``number`` optionally pins it to one
        box number (needed for come/don't-come). Prefer this over
        ``has_bet("pass_odds")`` — odds bets store the point number, so a
        plain ``has_bet`` lookup with ``number=None`` never matches them.
        """
        if kind not in _FLAT_FOR_ODDS:
            raise UnknownBetError(f"no odds exist for {kind!r}")
        odds_kind = _FLAT_FOR_ODDS[kind]
        return any(
            b.kind == odds_kind and (number is None or b.number == number)
            for b in self.bets
        )

    # ------------------------------------------------------------------
    # Rolling
    # ------------------------------------------------------------------
    def roll(self, d1: Optional[int] = None, d2: Optional[int] = None) -> CrapsRollResult:
        """Roll the dice (random unless ``d1``/``d2`` given) and settle bets."""
        if d1 is None or d2 is None:
            d1, d2 = self._die(), self._die()
        total = d1 + d2
        self.last_roll = (d1, d2)
        self.roll_count += 1
        self.shooter_rolls += 1

        events_before = len(self._events)
        for bet in list(self.bets):  # copy: settling mutates the list
            self._resolve_bet(bet, total, hard=(d1 == d2))

        # Phase transitions happen after every bet has seen the roll.
        if self.phase == "comeout" and total in POINT_NUMBERS:
            self.phase = "point"
            self.point = total
        elif self.phase == "point" and total in (7, self.point):
            seven_out = total == 7
            self.phase = "comeout"
            self.point = None
            if seven_out:
                self.shooter_rolls = 0  # new shooter

        return CrapsRollResult(
            description=f"{d1}-{d2} = {total} ({self.phase}"
            + (f", point {self.point}" if self.point else "")
            + ")",
            events=self._events[events_before:],
            d1=d1,
            d2=d2,
            total=total,
            phase=self.phase,
            point=self.point,
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def _resolve_bet(self, bet: Bet, total: int, hard: bool) -> None:
        kind, n = bet.kind, bet.number

        # -- one-roll bets: always live ---------------------------------
        if kind == "field":
            self._settle(bet, "won" if total in FIELD_PAY else "lost",
                         FIELD_PAY.get(total, 0.0))
            return
        if kind in PROP_PAY:
            won = total in PROP_WINNERS[kind]
            self._settle(bet, "won" if won else "lost",
                         PROP_PAY[kind] if won else 0.0)
            return

        # -- hardways: off on the come-out ------------------------------
        if kind == "hard":
            if self.phase == "comeout":
                return
            if total == 7 or total == n:
                if total == n and hard:
                    self._settle(bet, "won", HARD_PAY[n])
                else:
                    self._settle(bet, "lost")
            return

        # -- line & come bets -------------------------------------------
        if kind == "pass":
            if self.phase == "comeout":
                if total in (7, 11):
                    self._settle(bet, "won", 1.0)
                elif total in (2, 3, 12):
                    self._settle(bet, "lost")
            else:
                if total == 7:
                    self._settle(bet, "lost")
                elif total == self.point:
                    self._settle(bet, "won", 1.0)
            return

        if kind == "dontpass":
            if self.phase == "comeout":
                if total in (2, 3):
                    self._settle(bet, "won", 1.0)
                elif total == 12:
                    self._settle(bet, "push")
                elif total in (7, 11):
                    self._settle(bet, "lost")
            else:
                if total == 7:
                    self._settle(bet, "won", 1.0)
                elif total == self.point:
                    self._settle(bet, "lost")
            return

        if kind == "pass_odds":
            if total == 7:
                self._settle(bet, "lost")
            elif total == n:
                self._settle(bet, "won", ODDS_PAY[n])
            return

        if kind == "dontpass_odds":
            if total == 7:
                self._settle(bet, "won", LAY_PAY[n])
            elif total == n:
                self._settle(bet, "lost")
            return

        if kind == "come":
            if n is None:  # in transit: works like a fresh pass-line roll
                if total in (7, 11):
                    self._settle(bet, "won", 1.0)
                elif total in (2, 3, 12):
                    self._settle(bet, "lost")
                else:
                    bet.number = total
                    self._events.append(BetEvent(kind, total, bet.amount, "travel", 0.0))
            else:
                if total == 7:
                    self._settle(bet, "lost")
                elif total == n:
                    self._settle(bet, "won", 1.0)
            return

        if kind == "dontcome":
            if n is None:
                if total in (2, 3):
                    self._settle(bet, "won", 1.0)
                elif total == 12:
                    self._settle(bet, "push")
                elif total in (7, 11):
                    self._settle(bet, "lost")
                else:
                    bet.number = total
                    self._events.append(BetEvent(kind, total, bet.amount, "travel", 0.0))
            else:
                if total == 7:
                    self._settle(bet, "won", 1.0)
                elif total == n:
                    self._settle(bet, "lost")
            return

        if kind == "come_odds":
            if total == 7:
                self._settle(bet, "lost")
            elif total == n:
                self._settle(bet, "won", ODDS_PAY[n])
            return

        if kind == "dontcome_odds":
            if total == 7:
                self._settle(bet, "won", LAY_PAY[n])
            elif total == n:
                self._settle(bet, "lost")
            return

        # -- place / buy / lay: off on the come-out ----------------------
        if kind in ("place", "buy", "lay"):
            if self.phase == "comeout":
                return
            if kind == "place":
                if total == n:
                    self._settle(bet, "won", PLACE_PAY[n])
                elif total == 7:
                    self._settle(bet, "lost")
            elif kind == "buy":
                if total == n:
                    self._settle(bet, "won", BUY_PAY[n])
                elif total == 7:
                    self._settle(bet, "lost")
            else:  # lay
                if total == 7:
                    self._settle(bet, "won", LAY_BET_PAY[n])
                elif total == n:
                    self._settle(bet, "lost")
            return

        raise UnknownBetError(f"cannot resolve unknown bet kind: {kind!r}")
