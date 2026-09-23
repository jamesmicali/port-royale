"""Shared base classes for casino game tables.

Every game in Port Royale exposes a *table* object with the same small
interface so the strategy framework and the Monte Carlo engine can drive
any game without knowing its rules:

- ``table.bankroll`` / ``table.bets`` — observable state
- ``strategy.decide(table)`` — the strategy places / removes bets
- ``table.roll()`` — the game resolves one round and settles all bets
- ``table.drain_events()`` — resolved-bet outcomes since the last call,
  which stateful strategies (e.g. "press after two wins") use as memory
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class TableError(Exception):
    """Base class for table errors (bad bets, broken limits, ...)."""


class InsufficientBankroll(TableError):
    """Raised when a bet costs more than the current bankroll."""


class TableLimitError(TableError):
    """Raised when a bet violates min/max limits or placement rules."""


class UnknownBetError(TableError):
    """Raised when a bet kind is not recognised by the game."""


@dataclass
class Bet:
    """A single live wager on the table."""

    kind: str
    amount: float
    number: Optional[int] = None  # point/box number, when the bet needs one


@dataclass
class BetEvent:
    """What happened to one bet when a round resolved."""

    kind: str
    number: Optional[int]
    amount: float          # stake that was at risk
    outcome: str           # "won" | "lost" | "push" | "returned" | "travel"
    profit: float          # net profit to the player (negative on a loss)

    def __str__(self) -> str:  # handy for debugging strategies
        num = f" {self.number}" if self.number else ""
        return f"{self.kind}{num} ${self.amount:g} -> {self.outcome} ({self.profit:+g})"


@dataclass
class RoundResult:
    """Summary of one resolved round, for logging / debugging."""

    description: str = ""
    events: list = field(default_factory=list)


class Table(ABC):
    """Abstract casino table.

    Concrete games implement :meth:`roll` (resolve one round) and the
    bet-placement helpers that make sense for them. The engine tracks
    ``bankroll``, ``total_wagered`` (every dollar ever put at risk — the
    denominator for realized house edge) and a queue of :class:`BetEvent`.
    """

    def __init__(self, bankroll: float = 1000.0, rng: Any = None) -> None:
        self.bankroll: float = float(bankroll)
        self.starting_bankroll: float = float(bankroll)
        self.bets: list[Bet] = []
        self.total_wagered: float = 0.0
        self._events: list[BetEvent] = []
        self.rng = rng

    # -- helpers shared by every game ------------------------------------
    def find_bet(self, kind: str, number: Optional[int] = None) -> Optional[Bet]:
        for bet in self.bets:
            if bet.kind == kind and bet.number == number:
                return bet
        return None

    def has_bet(self, kind: str, number: Optional[int] = None) -> bool:
        return self.find_bet(kind, number) is not None

    def drain_events(self) -> list[BetEvent]:
        """Return and clear the resolved-bet events since the last call."""
        events = self._events
        self._events = []
        return events

    def _charge(self, amount: float) -> None:
        if amount > self.bankroll + 1e-9:
            raise InsufficientBankroll(
                f"bet of ${amount:g} exceeds bankroll of ${self.bankroll:g}"
            )
        self.bankroll -= amount
        self.total_wagered += amount

    def _settle(self, bet: Bet, outcome: str, pay_mult: float = 0.0) -> BetEvent:
        """Remove *bet* and move money. ``pay_mult`` is profit per unit staked."""
        self.bets.remove(bet)
        if outcome == "won":
            profit = bet.amount * pay_mult
            self.bankroll += bet.amount + profit
        elif outcome == "push":
            profit = 0.0
            self.bankroll += bet.amount
        elif outcome == "returned":
            profit = 0.0
            self.bankroll += bet.amount
        else:  # lost
            profit = -bet.amount
        event = BetEvent(bet.kind, bet.number, bet.amount, outcome, profit)
        self._events.append(event)
        return event

    @abstractmethod
    def roll(self, *args: Any, **kwargs: Any) -> RoundResult:
        """Resolve one round of the game and settle every bet."""
        raise NotImplementedError
