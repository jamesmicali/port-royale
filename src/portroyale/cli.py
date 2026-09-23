"""Command-line interface: ``portroyale run`` / ``watch`` / ``compare`` / ``strategies``."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .games import list_games
from .sim import (
    SimConfig,
    TableConfig,
    format_comparison,
    format_report,
    run_comparison,
    run_simulation,
    watch_session,
)
from .strategies import STRATEGIES, list_strategies


def _parse_params(pairs: list[str], strategy_name: str) -> dict:
    from .strategies import STRATEGIES

    spec = STRATEGIES[strategy_name].PARAMS
    cast = {"int": int, "float": float, "bool": bool, "str": str}
    params: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--param expects KEY=VALUE, got {pair!r}")
        key, value = pair.split("=", 1)
        if key not in spec:
            raise ValueError(
                f"unknown param {key!r} for {strategy_name}; "
                f"available: {sorted(spec)}"
            )
        params[key] = cast[spec[key].get("type", "float")](value)
    return params


def cmd_run(args: argparse.Namespace) -> int:
    config = SimConfig(
        game=args.game,
        strategy=args.strategy,
        strategy_params=_parse_params(args.param, args.strategy),
        bankroll=args.bankroll,
        table=TableConfig(
            min_bet=args.min_bet,
            max_bet=args.max_bet,
            odds_multiple=args.odds_multiple,
        ),
        rolls=args.rolls,
        sessions=args.sessions,
        seed=args.seed,
        stop_loss=args.stop_loss,
        stop_win=args.stop_win,
        workers=args.workers,
    )
    print(f"Running {args.sessions} sessions x {args.rolls} rolls "
          f"({args.workers or 'auto'} workers)...", flush=True)
    report = run_simulation(config)
    print()
    print(format_report(report))
    return 0


def _money(x: float) -> str:
    return f"${x:,.2f}"


def cmd_watch(args: argparse.Namespace) -> int:
    gen = watch_session(
        game=args.game,
        strategy=args.strategy,
        seed=args.seed,
        bankroll=args.bankroll,
        rolls=args.rolls,
        stop_loss=args.stop_loss,
        stop_win=args.stop_win,
        params=_parse_params(args.param, args.strategy),
        min_bet=args.min_bet,
        max_bet=args.max_bet,
        odds_multiple=args.odds_multiple,
    )
    placed: list[str] = []
    resolved: list[str] = []
    for ev in gen:
        kind = ev["type"]
        if kind == "session_start":
            stops = []
            if ev["stop_loss"]:
                stops.append(f"stop-loss {ev['stop_loss']:.0%}")
            if ev["stop_win"]:
                stops.append(f"stop-win {ev['stop_win']:.0%}")
            stop_txt = f" ({', '.join(stops)})" if stops else ""
            print(f"Watching {ev['game']} / {ev['strategy']} — "
                  f"seed {ev['seed']}, bankroll {_money(ev['bankroll'])}, "
                  f"{ev['rolls']} rolls{stop_txt}")
        elif kind == "bet_placed":
            num = f" on {ev['number']}" if ev["number"] else ""
            placed.append(f"{ev['kind']}{num} {_money(ev['amount'])}")
        elif kind == "bet_resolved":
            num = f" {ev['number']}" if ev["number"] else ""
            sign = "+" if ev["profit"] >= 0 else ""
            resolved.append(f"{ev['kind']}{num} {_money(ev['amount'])} → "
                            f"{ev['outcome']} ({sign}{_money(ev['profit'])})")
        elif kind == "roll":
            point = f", point {ev['point']}" if ev["point"] else ""
            print(f"[{ev['roll']}] {ev['phase']}{point}: "
                  f"{ev['d1']}-{ev['d2']} = {ev['total']}")
        elif kind == "bankroll":
            bits = []
            if placed:
                bits.append("placed " + ", ".join(placed))
                placed = []
            if resolved:
                bits.append("; ".join(resolved))
                resolved = []
            bits.append(f"bankroll {_money(ev['bankroll'])}")
            print("    " + " · ".join(bits))
        elif kind == "session_end":
            print(f"— session over after {ev['rolls_played']} rolls "
                  f"({ev['reason']}); final {_money(ev['final_bankroll'])} "
                  f"({ev['net_profit']:+.2f})")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    names = [s.strip() for s in args.strategies.split(",") if s.strip()]
    unknown = [n for n in names if n not in STRATEGIES]
    if unknown:
        raise ValueError(f"unknown strategies: {unknown}; "
                         f"available: {sorted(STRATEGIES)}")
    print(f"Comparing {', '.join(names)} — {args.sessions} sessions x "
          f"{args.rolls} rolls, identical dice "
          f"({args.workers or 'auto'} workers)...", flush=True)
    report = run_comparison(
        game=args.game,
        strategies=names,
        bankroll=args.bankroll,
        table=TableConfig(
            min_bet=args.min_bet,
            max_bet=args.max_bet,
            odds_multiple=args.odds_multiple,
        ),
        rolls=args.rolls,
        sessions=args.sessions,
        seed=args.seed,
        stop_loss=args.stop_loss,
        stop_win=args.stop_win,
        workers=args.workers,
    )
    print()
    print(format_comparison(report))
    return 0


def cmd_strategies(_args: argparse.Namespace) -> int:
    for cls in list_strategies():
        print(f"{cls.name}\n  {cls.description}")
        for key, spec in cls.PARAMS.items():
            print(f"    {key} ({spec.get('type', 'float')}, "
                  f"default={spec.get('default')}) — {spec.get('help', '')}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="portroyale",
        description=f"Port Royale {__version__} — casino strategy lab",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Monte Carlo a strategy")
    run.add_argument("--game", default="craps", choices=list_games())
    run.add_argument("--strategy", default="passline_odds",
                     help="strategy name (see `portroyale strategies`)")
    run.add_argument("--bankroll", type=float, default=1000.0)
    run.add_argument("--rolls", type=int, default=10_000,
                     help="rolls per session")
    run.add_argument("--sessions", type=int, default=500)
    run.add_argument("--seed", type=int, default=None,
                     help="base RNG seed for reproducibility")
    run.add_argument("--stop-loss", type=float, default=None,
                     help="end a session at <= this fraction of starting bankroll")
    run.add_argument("--stop-win", type=float, default=None,
                     help="end a session at >= this fraction of starting bankroll")
    run.add_argument("--workers", type=int, default=0,
                     help="parallel workers (0 = all CPUs)")
    run.add_argument("--min-bet", type=float, default=5.0)
    run.add_argument("--max-bet", type=float, default=5000.0)
    run.add_argument("--odds-multiple", type=int, default=5)
    run.add_argument("--param", action="append", default=[],
                     help="strategy param as KEY=VALUE (repeatable)")
    run.set_defaults(func=cmd_run)

    ls = sub.add_parser("strategies", help="list available strategies")
    ls.set_defaults(func=cmd_strategies)

    watch = sub.add_parser("watch", help="watch one session play out roll by roll")
    watch.add_argument("--game", default="craps", choices=list_games())
    watch.add_argument("--strategy", default="passline_odds",
                       help="strategy name (see `portroyale strategies`)")
    watch.add_argument("--seed", type=int, default=42,
                       help="session seed (same seed = same session)")
    watch.add_argument("--bankroll", type=float, default=1000.0)
    watch.add_argument("--rolls", type=int, default=300,
                       help="max rolls to play")
    watch.add_argument("--stop-loss", type=float, default=None,
                       help="end session at <= this fraction of starting bankroll")
    watch.add_argument("--stop-win", type=float, default=None,
                       help="end session at >= this fraction of starting bankroll")
    watch.add_argument("--min-bet", type=float, default=5.0)
    watch.add_argument("--max-bet", type=float, default=5000.0)
    watch.add_argument("--odds-multiple", type=int, default=5)
    watch.add_argument("--param", action="append", default=[],
                       help="strategy param as KEY=VALUE (repeatable)")
    watch.set_defaults(func=cmd_watch)

    cmp = sub.add_parser("compare", help="A/B strategies on identical dice")
    cmp.add_argument("--game", default="craps", choices=list_games())
    cmp.add_argument("--strategies", required=True,
                     help="comma-separated strategy names, e.g. passline_odds,ironcross")
    cmp.add_argument("--bankroll", type=float, default=1000.0)
    cmp.add_argument("--rolls", type=int, default=5000,
                     help="rolls per session")
    cmp.add_argument("--sessions", type=int, default=100)
    cmp.add_argument("--seed", type=int, default=None,
                     help="master seed — REQUIRED (identical dice need a seed)")
    cmp.add_argument("--stop-loss", type=float, default=None,
                     help="end a session at <= this fraction of starting bankroll")
    cmp.add_argument("--stop-win", type=float, default=None,
                     help="end a session at >= this fraction of starting bankroll")
    cmp.add_argument("--workers", type=int, default=0,
                     help="parallel workers (0 = all CPUs)")
    cmp.add_argument("--min-bet", type=float, default=5.0)
    cmp.add_argument("--max-bet", type=float, default=5000.0)
    cmp.add_argument("--odds-multiple", type=int, default=5)
    cmp.set_defaults(func=cmd_compare)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
