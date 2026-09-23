"""Monte Carlo simulation engine.

A *session* is one run of a strategy: start with a bankroll, let the
strategy bet before every round, resolve the round, and repeat for ``rolls``
rounds (or until the bankroll can no longer cover the table minimum —
that's a ruin). ``run_simulation`` repeats the session ``sessions`` times,
optionally across multiple processes, and aggregates everything into a
:class:`SimReport` with the statistics that matter for a strategy:

- realized house edge (net loss per dollar wagered — the number the math
  says your strategy *actually* pays),
- session win rate, risk of ruin, max drawdown,
- percentiles of final bankrolls, plus percentile bands over time for
  charts.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from .games import make_table
from .games.base import InsufficientBankroll, TableError
from .strategies import make_strategy

HISTORY_POINTS = 400  # bankroll samples kept per session (for charts)


@dataclass
class TableConfig:
    min_bet: float = 5.0
    max_bet: float = 5000.0
    odds_multiple: int = 5


@dataclass
class SimConfig:
    game: str = "craps"
    strategy: str = "passline_odds"
    strategy_params: dict = field(default_factory=dict)
    bankroll: float = 1000.0
    table: TableConfig = field(default_factory=TableConfig)
    rolls: int = 10_000
    sessions: int = 500
    seed: Optional[int] = None
    workers: int = 0  # 0 -> os.cpu_count()

    def as_dict(self) -> dict:
        return {
            "game": self.game,
            "strategy": self.strategy,
            "strategy_params": dict(self.strategy_params),
            "bankroll": self.bankroll,
            "table": {
                "min_bet": self.table.min_bet,
                "max_bet": self.table.max_bet,
                "odds_multiple": self.table.odds_multiple,
            },
            "rolls": self.rolls,
            "sessions": self.sessions,
            "seed": self.seed,
        }


@dataclass
class SessionResult:
    final_bankroll: float
    profit: float
    action: float          # total dollars wagered
    edge: float            # realized house edge for this session (-profit/action)
    max_drawdown: float
    ruined: bool
    rolls_played: int
    history: list[float]   # downsampled bankroll trajectory


def run_session(cfg: dict, session_index: int) -> SessionResult:
    """Run one session. Module-level so it pickles for multiprocessing."""
    seed = cfg["seed"]
    rng = np.random.default_rng() if seed is None else np.random.default_rng(seed + session_index)
    t = cfg["table"]
    table = make_table(
        cfg["game"],
        bankroll=cfg["bankroll"],
        min_bet=t["min_bet"],
        max_bet=t["max_bet"],
        odds_multiple=t["odds_multiple"],
        rng=rng,
    )
    strategy = make_strategy(cfg["strategy"], **cfg["strategy_params"])
    strategy.on_session_start(table)

    start = cfg["bankroll"]
    # Sample at most HISTORY_POINTS points; pad short runs to equal length.
    step = max(1, -(-cfg["rolls"] // HISTORY_POINTS))  # ceiling division
    history = [start]
    peak = start
    max_dd = 0.0
    ruined = False
    rolls_played = 0

    for r in range(1, cfg["rolls"] + 1):
        if table.bankroll < table.min_bet - 1e-9:
            ruined = True
            break
        try:
            strategy.decide(table)
            table.roll()
        except (InsufficientBankroll, TableError):
            # Strategy bug or broke mid-round: stop the session here.
            ruined = table.bankroll < table.min_bet
            break
        rolls_played = r
        peak = max(peak, table.bankroll)
        max_dd = max(max_dd, peak - table.bankroll)
        if r % step == 0 or r == cfg["rolls"]:
            history.append(table.bankroll)

    # Pad the trajectory so every session lines up for percentile bands.
    while len(history) < HISTORY_POINTS + 1:
        history.append(history[-1])

    profit = table.bankroll - start
    action = table.total_wagered
    edge = -profit / action if action > 0 else 0.0
    return SessionResult(
        final_bankroll=table.bankroll,
        profit=profit,
        action=action,
        edge=edge,
        max_drawdown=max_dd,
        ruined=ruined,
        rolls_played=rolls_played,
        history=history,
    )


@dataclass
class SimReport:
    config: SimConfig
    sessions: int
    mean_final: float
    median_final: float
    p5_final: float
    p25_final: float
    p75_final: float
    p95_final: float
    mean_profit: float
    total_action: float
    realized_edge: float      # -total_profit / total_action
    win_rate: float           # fraction of sessions finishing above start
    ruin_rate: float          # fraction of sessions ruined
    mean_max_drawdown: float
    median_rolls_played: float
    bands: dict[str, list[float]]  # p5/p25/p50/p75/p95 bankroll over time


def run_simulation(config: SimConfig, progress: Any = None) -> SimReport:
    """Run ``config.sessions`` sessions, in parallel, and aggregate."""
    cfg = config.as_dict()
    workers = config.workers or os.cpu_count() or 1

    if workers == 1:
        results = [run_session(cfg, i) for i in range(config.sessions)]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(run_session, [cfg] * config.sessions,
                                    range(config.sessions)))

    finals = np.array([r.final_bankroll for r in results])
    profits = np.array([r.profit for r in results])
    actions = np.array([r.action for r in results])
    histories = np.array([r.history for r in results])  # (sessions, points)

    total_profit = float(profits.sum())
    total_action = float(actions.sum())
    bands = {
        "p5": np.percentile(histories, 5, axis=0).tolist(),
        "p25": np.percentile(histories, 25, axis=0).tolist(),
        "p50": np.percentile(histories, 50, axis=0).tolist(),
        "p75": np.percentile(histories, 75, axis=0).tolist(),
        "p95": np.percentile(histories, 95, axis=0).tolist(),
    }
    return SimReport(
        config=config,
        sessions=len(results),
        mean_final=float(finals.mean()),
        median_final=float(np.median(finals)),
        p5_final=float(np.percentile(finals, 5)),
        p25_final=float(np.percentile(finals, 25)),
        p75_final=float(np.percentile(finals, 75)),
        p95_final=float(np.percentile(finals, 95)),
        mean_profit=float(profits.mean()),
        total_action=total_action,
        realized_edge=(-total_profit / total_action) if total_action > 0 else 0.0,
        win_rate=float(np.mean(finals > config.bankroll)),
        ruin_rate=float(np.mean([r.ruined for r in results])),
        mean_max_drawdown=float(np.mean([r.max_drawdown for r in results])),
        median_rolls_played=float(np.median([r.rolls_played for r in results])),
        bands=bands,
    )


def format_report(report: SimReport) -> str:
    """Render a SimReport as a plain-text summary (used by the CLI)."""
    c = report.config
    params = ", ".join(f"{k}={v}" for k, v in c.strategy_params.items())
    lines = [
        f"Port Royale — {c.game} / {c.strategy}" + (f" ({params})" if params else ""),
        f"Sessions: {report.sessions}   Rolls/session: {c.rolls}   "
        f"Bankroll: ${c.bankroll:,.2f}",
        "-" * 60,
        f"Median final bankroll:  ${report.median_final:>12,.2f}",
        f"Mean final bankroll:    ${report.mean_final:>12,.2f}",
        f"Mean net profit:        ${report.mean_profit:>+12,.2f}",
        f"Total action:           ${report.total_action:>12,.2f}",
        f"Realized house edge:    {report.realized_edge:>11.2%}  (per $ wagered)",
        f"Session win rate:       {report.win_rate:>11.1%}",
        f"Risk of ruin:           {report.ruin_rate:>11.1%}",
        f"Mean max drawdown:      ${report.mean_max_drawdown:>12,.2f}",
        "Final bankroll percentiles:",
        f"   p5 ${report.p5_final:,.2f}   p25 ${report.p25_final:,.2f}   "
        f"p75 ${report.p75_final:,.2f}   p95 ${report.p95_final:,.2f}",
    ]
    return "\n".join(lines)
