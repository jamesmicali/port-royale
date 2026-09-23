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

Reproducibility
---------------
Every session is fully determined by its seed. ``SimConfig.seed`` is a
*master* seed; session ``i`` plays the dice stream drawn from
``random.Random(master_seed + i)``. Re-running with the same master seed
reproduces the run exactly — same event streams, same statistics.

Watch mode
----------
:func:`watch_session` plays a single session and yields a stream of
JSON-serializable event dicts (the cross-platform contract the future
mobile table UI consumes — see ``docs/watch-mode.md``). ``run_session``
is built on the same generator, so the simulator and the viewer can
never disagree about what happened.

Comparison mode
---------------
:func:`run_comparison` runs several strategies against the *identical*
dice streams (common random numbers): each session's dice are generated
once from the seed and replayed for every strategy. Shared randomness
cancels out most of the luck, so differences in the results are
differences in the strategies, not the dice.
"""
from __future__ import annotations

import os
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import numpy as np

from .games import make_table
from .games.base import InsufficientBankroll, TableError
from .strategies import make_strategy

HISTORY_POINTS = 400  # bankroll samples kept per session (for charts)

# Session end reasons (also the ``reason`` values in watch-mode events).
REASON_EXHAUSTED = "rolls_exhausted"
REASON_RUIN = "ruin"
REASON_STOP_LOSS = "stop_loss"
REASON_STOP_WIN = "stop_win"
REASON_ERROR = "error"


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
    stop_loss: Optional[float] = None  # end session at <= this fraction of start
    stop_win: Optional[float] = None   # end session at >= this fraction of start
    workers: int = 0  # 0 -> os.cpu_count()

    def __post_init__(self) -> None:
        for name in ("stop_loss", "stop_win"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")

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
            "stop_loss": self.stop_loss,
            "stop_win": self.stop_win,
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
    end_reason: str        # one of the REASON_* constants
    seed: Optional[int]    # session seed (None when unseeded)
    history: list[float]   # downsampled bankroll trajectory


def session_seed(master_seed: Optional[int], session_index: int) -> Optional[int]:
    """Derive a session's seed deterministically from the master seed."""
    return None if master_seed is None else master_seed + session_index


def make_dice_stream(seed: int, n: int) -> list[tuple[int, int]]:
    """Generate ``n`` dice pairs from ``seed``. Shared by sim and compare."""
    rng = random.Random(seed)
    return [(rng.randint(1, 6), rng.randint(1, 6)) for _ in range(n)]


def _bet_placed_event(roll_no: int, bet) -> dict:
    return {
        "type": "bet_placed",
        "roll": roll_no,
        "kind": bet.kind,
        "amount": float(bet.amount),
        "number": bet.number,
    }


def _bet_resolved_event(roll_no: int, event) -> dict:
    return {
        "type": "bet_resolved",
        "roll": roll_no,
        "kind": event.kind,
        "number": event.number,
        "amount": float(event.amount),
        "outcome": event.outcome,  # won | lost | push | returned | travel
        "profit": float(event.profit),
    }


def _iter_session_events(
    cfg: dict,
    session_index: int,
    dice: Optional[list[tuple[int, int]]] = None,
) -> Iterator[dict]:
    """Play one session, yielding JSON-serializable event dicts.

    This generator is the single source of truth for "what happened in a
    session": :func:`run_session` aggregates it into statistics and
    :func:`watch_session` exposes it directly, so the simulator and any
    viewer (CLI, Streamlit, the future mobile table) always agree.

    Event types: ``session_start``, ``bet_placed``, ``bet_resolved``,
    ``roll``, ``bankroll``, ``session_end``. Full schema documented in
    ``docs/watch-mode.md``.
    """
    seed = session_seed(cfg["seed"], session_index)
    if dice is None and seed is not None:
        dice = make_dice_stream(seed, cfg["rolls"])
    t = cfg["table"]
    table = make_table(
        cfg["game"],
        bankroll=cfg["bankroll"],
        min_bet=t["min_bet"],
        max_bet=t["max_bet"],
        odds_multiple=t["odds_multiple"],
    )
    strategy = make_strategy(cfg["strategy"], **cfg["strategy_params"])
    strategy.on_session_start(table)

    start = float(cfg["bankroll"])
    stop_loss = cfg.get("stop_loss")
    stop_win = cfg.get("stop_win")

    yield {
        "type": "session_start",
        "game": cfg["game"],
        "strategy": cfg["strategy"],
        "strategy_params": {k: v for k, v in cfg["strategy_params"].items()},
        "seed": seed,
        "bankroll": start,
        "rolls": cfg["rolls"],
        "stop_loss": stop_loss,
        "stop_win": stop_win,
        "min_bet": float(t["min_bet"]),
        "max_bet": float(t["max_bet"]),
        "odds_multiple": int(t["odds_multiple"]),
    }

    peak = start
    max_dd = 0.0
    rolls_played = 0
    reason = REASON_EXHAUSTED
    error: Optional[str] = None

    for r in range(1, cfg["rolls"] + 1):
        if table.bankroll < table.min_bet - 1e-9:
            reason = REASON_RUIN
            break
        known_ids = {id(b) for b in table.bets}
        try:
            strategy.decide(table)
        except (InsufficientBankroll, TableError) as exc:
            reason = REASON_ERROR
            error = str(exc)
            break
        for bet in table.bets:
            if id(bet) not in known_ids:
                yield _bet_placed_event(r, bet)
        for event in table.drain_events():  # take-downs / adjustments in decide()
            yield _bet_resolved_event(r, event)

        if dice is not None:
            d1, d2 = dice[r - 1]
            result = table.roll(d1, d2)
        else:
            result = table.roll()
        yield {
            "type": "roll",
            "roll": r,
            "d1": int(result.d1),
            "d2": int(result.d2),
            "total": int(result.total),
            "phase": result.phase,   # phase *after* the roll resolved
            "point": result.point,   # point *after* the roll resolved
        }
        for event in table.drain_events():
            yield _bet_resolved_event(r, event)

        rolls_played = r
        peak = max(peak, table.bankroll)
        max_dd = max(max_dd, peak - table.bankroll)
        yield {"type": "bankroll", "roll": r, "bankroll": float(table.bankroll)}

        if stop_win is not None and table.bankroll >= stop_win * start - 1e-9:
            reason = REASON_STOP_WIN
            break
        if stop_loss is not None and table.bankroll <= stop_loss * start + 1e-9:
            reason = REASON_STOP_LOSS
            break

    end_event: dict[str, Any] = {
        "type": "session_end",
        "reason": reason,
        "rolls_played": rolls_played,
        "final_bankroll": float(table.bankroll),
        "net_profit": float(table.bankroll - start),
        "total_wagered": float(table.total_wagered),
        "max_drawdown": float(max_dd),
    }
    if error is not None:
        end_event["error"] = error
    yield end_event


def watch_session(
    game: str = "craps",
    strategy: str = "passline_odds",
    seed: int = 42,
    bankroll: float = 1000.0,
    rolls: int = 300,
    stop_loss: Optional[float] = None,
    stop_win: Optional[float] = None,
    params: Optional[dict] = None,
    min_bet: float = 5.0,
    max_bet: float = 5000.0,
    odds_multiple: int = 5,
    dice: Optional[list[tuple[int, int]]] = None,
) -> Iterator[dict]:
    """Play ONE session, yielding the per-roll event stream.

    Every yielded dict is JSON-serializable (``json.dumps`` it) — this
    stream is the cross-platform contract the future mobile table
    consumes. See ``docs/watch-mode.md`` for the event schema.
    """
    if stop_loss is not None and stop_loss <= 0:
        raise ValueError(f"stop_loss must be positive, got {stop_loss}")
    if stop_win is not None and stop_win <= 0:
        raise ValueError(f"stop_win must be positive, got {stop_win}")
    cfg = {
        "game": game,
        "strategy": strategy,
        "strategy_params": dict(params or {}),
        "bankroll": bankroll,
        "table": {
            "min_bet": min_bet,
            "max_bet": max_bet,
            "odds_multiple": odds_multiple,
        },
        "rolls": rolls,
        "sessions": 1,
        "seed": seed,
        "stop_loss": stop_loss,
        "stop_win": stop_win,
    }
    return _iter_session_events(cfg, 0, dice=dice)


def run_session(
    cfg: dict,
    session_index: int,
    dice: Optional[list[tuple[int, int]]] = None,
) -> SessionResult:
    """Run one session. Module-level so it pickles for multiprocessing.

    Consumes the same event generator as :func:`watch_session`, so
    simulated statistics and the visible play-by-play always agree.
    """
    seed = session_seed(cfg["seed"], session_index)
    start = float(cfg["bankroll"])
    # Sample at most HISTORY_POINTS points; pad short runs to equal length.
    step = max(1, -(-cfg["rolls"] // HISTORY_POINTS))  # ceiling division
    history = [start]
    end_reason = REASON_EXHAUSTED
    final = start
    profit = 0.0
    action = 0.0
    max_dd = 0.0
    rolls_played = 0

    for event in _iter_session_events(cfg, session_index, dice=dice):
        etype = event["type"]
        if etype == "bankroll":
            r = event["roll"]
            if r % step == 0 or r == cfg["rolls"]:
                history.append(event["bankroll"])
        elif etype == "session_end":
            end_reason = event["reason"]
            final = event["final_bankroll"]
            profit = event["net_profit"]
            action = event["total_wagered"]
            max_dd = event["max_drawdown"]
            rolls_played = event["rolls_played"]
            if rolls_played % step != 0:
                history.append(final)

    # Pad the trajectory so every session lines up for percentile bands.
    while len(history) < HISTORY_POINTS + 1:
        history.append(history[-1])

    edge = -profit / action if action > 0 else 0.0
    return SessionResult(
        final_bankroll=final,
        profit=profit,
        action=action,
        edge=edge,
        max_drawdown=max_dd,
        ruined=end_reason == REASON_RUIN,
        rolls_played=rolls_played,
        end_reason=end_reason,
        seed=seed,
        history=history,
    )


def _aggregate(results: list[SessionResult], config: SimConfig) -> "SimReport":
    """Aggregate per-session results into a SimReport."""
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
    end_reasons: dict[str, float] = {}
    for r in results:
        end_reasons[r.end_reason] = end_reasons.get(r.end_reason, 0.0) + 1.0
    n = max(1, len(results))
    end_reasons = {k: v / n for k, v in end_reasons.items()}
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
        end_reasons=end_reasons,
        bands=bands,
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
    end_reasons: dict[str, float]  # reason -> fraction of sessions
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

    return _aggregate(results, config)


def _format_end_reasons(end_reasons: dict[str, float]) -> str:
    parts = [f"{reason} {frac:.1%}" for reason, frac in
             sorted(end_reasons.items(), key=lambda kv: -kv[1]) if frac > 0]
    return " · ".join(parts)


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
        f"Session end reasons:    {_format_end_reasons(report.end_reasons)}",
        "Final bankroll percentiles:",
        f"   p5 ${report.p5_final:,.2f}   p25 ${report.p25_final:,.2f}   "
        f"p75 ${report.p75_final:,.2f}   p95 ${report.p95_final:,.2f}",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ compare --
def _compare_session(
    payload: tuple[dict[str, dict], int, list[tuple[int, int]]],
) -> dict[str, SessionResult]:
    """Run one session index for every strategy on the same dice.

    Module-level so it pickles for multiprocessing.
    """
    cfgs, session_index, dice = payload
    return {name: run_session(cfg, session_index, dice=dice)
            for name, cfg in cfgs.items()}


@dataclass
class ComparisonReport:
    game: str
    strategies: list[str]
    sessions: int
    rolls: int
    bankroll: float
    seed: int
    reports: dict[str, SimReport]  # strategy name -> SimReport

    def table_rows(self) -> list[dict[str, Any]]:
        rows = []
        for name in self.strategies:
            r = self.reports[name]
            rows.append({
                "strategy": name,
                "edge": r.realized_edge,
                "win_rate": r.win_rate,
                "ruin_rate": r.ruin_rate,
                "mean_drawdown": r.mean_max_drawdown,
                "median_final": r.median_final,
                "p5_final": r.p5_final,
                "p95_final": r.p95_final,
                "end_reasons": r.end_reasons,
            })
        return rows


def run_comparison(
    game: str = "craps",
    strategies: Optional[list[str]] = None,
    strategy_params: Optional[dict[str, dict]] = None,
    bankroll: float = 1000.0,
    table: Optional[TableConfig] = None,
    rolls: int = 5000,
    sessions: int = 100,
    seed: Optional[int] = 7,
    stop_loss: Optional[float] = None,
    stop_win: Optional[float] = None,
    workers: int = 0,
) -> ComparisonReport:
    """Run several strategies against IDENTICAL dice streams.

    For session ``i`` the dice are generated once from
    ``random.Random(seed + i)`` and replayed for every strategy — common
    random numbers, so result differences reflect strategy differences,
    not luck. A seed is required: without shared dice the comparison
    would just measure noise.
    """
    if seed is None:
        raise ValueError(
            "compare requires a seed — identical dice are the whole point "
            "(pass --seed N)"
        )
    strategies = list(strategies or ["passline_odds"])
    if len(strategies) < 2:
        raise ValueError("compare needs at least two strategies")
    table = table or TableConfig()
    strategy_params = strategy_params or {}

    cfgs: dict[str, dict] = {}
    configs: dict[str, SimConfig] = {}
    for name in strategies:
        sc = SimConfig(
            game=game, strategy=name,
            strategy_params=dict(strategy_params.get(name, {})),
            bankroll=bankroll, table=table, rolls=rolls, sessions=sessions,
            seed=seed, stop_loss=stop_loss, stop_win=stop_win,
        )
        cfgs[name] = sc.as_dict()
        configs[name] = sc

    workers = workers or os.cpu_count() or 1
    payloads = [
        (cfgs, i, make_dice_stream(seed + i, rolls)) for i in range(sessions)
    ]
    if workers == 1:
        per_session = [_compare_session(p) for p in payloads]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            per_session = list(pool.map(_compare_session, payloads))

    reports = {}
    for name in strategies:
        results = [per_session[i][name] for i in range(sessions)]
        reports[name] = _aggregate(results, configs[name])
    return ComparisonReport(
        game=game, strategies=strategies, sessions=sessions, rolls=rolls,
        bankroll=bankroll, seed=seed, reports=reports,
    )


def format_comparison(report: ComparisonReport) -> str:
    """Render a ComparisonReport as a side-by-side plain-text table."""
    lines = [
        f"Port Royale — compare on {report.game} "
        f"({report.sessions} sessions x {report.rolls} rolls, "
        f"bankroll ${report.bankroll:,.2f}, seed {report.seed})",
        "Identical dice for every strategy (common random numbers).",
        "-" * 92,
        f"{'Strategy':<16}{'Edge':>9}{'Win%':>8}{'Ruin%':>8}"
        f"{'MeanDD':>10}{'Median':>10}{'p5':>10}{'p95':>10}",
    ]
    for row in report.table_rows():
        lines.append(
            f"{row['strategy']:<16}{row['edge']:>8.2%} {row['win_rate']:>7.1%}"
            f" {row['ruin_rate']:>7.1%} ${row['mean_drawdown']:>9,.0f}"
            f" ${row['median_final']:>9,.0f} ${row['p5_final']:>9,.0f}"
            f" ${row['p95_final']:>9,.0f}"
        )
    lines.append("")
    lines.append("Session end reasons (% of sessions):")
    reasons = sorted({r for row in report.table_rows()
                      for r in row["end_reasons"]})
    header = f"{'Strategy':<16}" + "".join(f"{r:>14}" for r in reasons)
    lines.append(header)
    for row in report.table_rows():
        line = f"{row['strategy']:<16}" + "".join(
            f"{row['end_reasons'].get(r, 0.0):>13.1%}" for r in reasons)
        lines.append(line)
    return "\n".join(lines)
