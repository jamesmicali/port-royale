"""Game registry. Adding a game = new module + one line here."""

from .base import Bet, BetEvent, RoundResult, Table
from .craps import CrapsTable

GAMES: dict[str, type[Table]] = {
    "craps": CrapsTable,
}


def make_table(game: str, **kwargs) -> Table:
    try:
        cls = GAMES[game]
    except KeyError:
        raise ValueError(f"unknown game {game!r}; available: {sorted(GAMES)}") from None
    return cls(**kwargs)


def list_games() -> list[str]:
    return sorted(GAMES)


__all__ = [
    "Bet",
    "BetEvent",
    "CrapsTable",
    "GAMES",
    "RoundResult",
    "Table",
    "list_games",
    "make_table",
]
