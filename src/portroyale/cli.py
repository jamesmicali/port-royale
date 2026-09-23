"""Command-line interface: ``portroyale run`` / ``portroyale strategies``."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .games import list_games
from .sim import SimConfig, TableConfig, format_report, run_simulation
from .strategies import list_strategies


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
        workers=args.workers,
    )
    print(f"Running {args.sessions} sessions x {args.rolls} rolls "
          f"({args.workers or 'auto'} workers)...", flush=True)
    report = run_simulation(config)
    print()
    print(format_report(report))
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
