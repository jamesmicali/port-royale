#!/usr/bin/env python3
"""Generate fixed-dice cross-language test vectors for the TypeScript engine.

For each scenario this runs the Python reference engine
(:func:`portroyale.sim.watch_session`) on an explicit, fixed dice stream and
dumps the resulting event stream to ``fixtures/<name>.json``.

The TypeScript test ``mobile/engine/__tests__/crosslang.test.ts`` replays
the same dice through ``watchSession`` and compares event-for-event. Because
both sides play *explicit* dice, the PRNG difference (Mersenne Twister vs
mulberry32) is irrelevant — the vectors pin the *rules*: payouts, phase
transitions, odds, stop-loss/win, ruin, and the event schema itself.

Regenerate with:  python3 tests/crosslang/generate_fixtures.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from portroyale.sim import make_dice_stream, watch_session

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

# name, strategy, params, bankroll, rolls, seed, stop_loss, stop_win,
# dice_seed (fixed) or target_reason (probe candidate seeds until it hits)
SCENARIOS = [
    {
        "name": "passline_odds",
        "strategy": "passline_odds",
        "params": {},
        "bankroll": 1000.0,
        "rolls": 300,
        "seed": 7,
        "stop_loss": None,
        "stop_win": None,
        "dice_seed": 7,
    },
    {
        "name": "dontpass_odds",
        "strategy": "dontpass_odds",
        "params": {},
        "bankroll": 1000.0,
        "rolls": 300,
        "seed": 7,
        "stop_loss": None,
        "stop_win": None,
        "dice_seed": 7,  # same dice as passline: bar-12 pushes, lay odds
    },
    {
        "name": "ironcross",
        "strategy": "ironcross",
        "params": {},
        "bankroll": 1000.0,
        "rolls": 300,
        "seed": 7,
        "stop_loss": None,
        "stop_win": None,
        "dice_seed": 7,  # same dice: field + place 5/6/8 coverage
    },
    {
        "name": "presser",
        "strategy": "presser",
        "params": {},
        "bankroll": 1000.0,
        "rolls": 300,
        "seed": 7,
        "stop_loss": None,
        "stop_win": None,
        "dice_seed": 7,  # same dice: exercises the streak/press state machine
    },
    {
        "name": "stop_loss",
        "strategy": "passline_odds",
        "params": {},
        "bankroll": 1000.0,
        "rolls": 500,
        "seed": 13,
        "stop_loss": 0.5,
        "stop_win": None,
        "target_reason": "stop_loss",
    },
    {
        "name": "stop_win",
        "strategy": "passline_odds",
        "params": {},
        "bankroll": 1000.0,
        "rolls": 500,
        "seed": 21,
        "stop_loss": None,
        "stop_win": 1.5,
        "target_reason": "stop_win",
    },
    {
        "name": "ruin",
        "strategy": "passline_odds",
        "params": {},
        "bankroll": 50.0,
        "rolls": 300,
        "seed": 7,
        "stop_loss": None,
        "stop_win": None,
        "target_reason": "ruin",
    },
]


def run(scenario: dict, dice: list) -> list:
    return list(
        watch_session(
            strategy=scenario["strategy"],
            params=scenario["params"],
            seed=scenario["seed"],
            bankroll=scenario["bankroll"],
            rolls=scenario["rolls"],
            stop_loss=scenario["stop_loss"],
            stop_win=scenario["stop_win"],
            dice=dice,
        )
    )


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    for sc in SCENARIOS:
        if "dice_seed" in sc:
            dice_seed = sc["dice_seed"]
            dice = make_dice_stream(dice_seed, sc["rolls"])
            events = run(sc, dice)
        else:
            # Probe candidate dice seeds until the target end reason hits.
            dice_seed = None
            events = []
            for candidate in range(1000):
                dice = make_dice_stream(candidate, sc["rolls"])
                events = run(sc, dice)
                if events[-1]["reason"] == sc["target_reason"]:
                    dice_seed = candidate
                    break
            if dice_seed is None:
                raise RuntimeError(
                    f"no dice seed produced {sc['target_reason']} for {sc['name']}"
                )
            print(f"{sc['name']}: dice_seed={dice_seed} -> {events[-1]['reason']}")

        fixture = {
            "name": sc["name"],
            "generated_by": "tests/crosslang/generate_fixtures.py",
            "config": {
                "game": "craps",
                "strategy": sc["strategy"],
                "strategyParams": sc["params"],
                "bankroll": sc["bankroll"],
                "minBet": 5.0,
                "maxBet": 5000.0,
                "oddsMultiple": 5,
                "rolls": sc["rolls"],
                "seed": sc["seed"],
                "stopLoss": sc["stop_loss"],
                "stopWin": sc["stop_win"],
            },
            "dice": [list(pair) for pair in dice],
            "events": events,
        }
        path = FIXTURES / f"{sc['name']}.json"
        path.write_text(json.dumps(fixture, indent=2) + "\n")
        print(f"wrote {path} ({len(events)} events)")


if __name__ == "__main__":
    main()
