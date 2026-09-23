"""Strategy registry. Register a new strategy class here to expose it to
the CLI (``portroyale run --strategy <name>``) and the Streamlit app."""

from .base import Strategy
from .craps import DontPassWithOdds, IronCross, PassLineWithOdds, PressAfterWins

STRATEGIES: dict[str, type[Strategy]] = {
    cls.name: cls
    for cls in (PassLineWithOdds, DontPassWithOdds, IronCross, PressAfterWins)
}


def make_strategy(name: str, **params) -> Strategy:
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise ValueError(
            f"unknown strategy {name!r}; available: {sorted(STRATEGIES)}"
        ) from None
    return cls(**params)


def list_strategies() -> list[type[Strategy]]:
    return [STRATEGIES[name] for name in sorted(STRATEGIES)]


__all__ = [
    "STRATEGIES",
    "Strategy",
    "list_strategies",
    "make_strategy",
]
