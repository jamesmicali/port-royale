"""The strategy framework.

A strategy is a small object that watches the table and bets. Before every
round the engine calls ``strategy.decide(table)``; the strategy reads the
table state (phase, point, bankroll, live bets, recent events) and calls
``table.place_bet(...)`` / ``table.add_odds(...)`` / ``table.take_down(...)``
directly. Because ``decide`` is ordinary Python, strategies can branch on
anything — the point number, the bankroll, how the last bets resolved::

    class MyStrategy(Strategy):
        name = "my_strategy"

        def decide(self, table):
            if table.phase == "comeout":
                table.place_bet("pass", 10)
            elif table.point in (6, 8) and table.bankroll > 500:
                # branch: only press the inside numbers when we're ahead
                for n in (6, 8):
                    if not table.has_bet("place", n):
                        table.place_bet("place", 12, n)

Strategies may also keep memory between rounds (``on_session_start`` resets
it) and learn what just happened via ``table.drain_events()`` — see
``PressAfterWins`` in ``strategies/craps.py`` for a worked example.

Each strategy declares its knobs in ``PARAMS`` so the CLI (``--param``) and
the Streamlit app can configure it without touching code::

    PARAMS = {
        "base_unit": {"type": "float", "default": 10.0,
                      "label": "Base unit ($)", "help": "Flat bet size."},
    }
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Strategy(ABC):
    """Base class for all betting strategies."""

    name: str = "base"
    description: str = ""
    PARAMS: dict[str, dict[str, Any]] = {}

    def __init__(self, **params: Any) -> None:
        for key, spec in self.PARAMS.items():
            raw = params.pop(key, spec.get("default"))
            cast = {"int": int, "float": float, "bool": bool, "str": str}[
                spec.get("type", "float")
            ]
            setattr(self, key, cast(raw))
        if params:
            raise ValueError(f"unknown params for {self.name}: {sorted(params)}")

    def on_session_start(self, table) -> None:
        """Reset any per-session memory. Called once before the first roll."""

    @abstractmethod
    def decide(self, table) -> None:
        """Observe the table and place / adjust bets before the next round."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        args = ", ".join(f"{k}={getattr(self, k)!r}" for k in self.PARAMS)
        return f"{type(self).__name__}({args})"
