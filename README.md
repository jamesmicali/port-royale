# 🎲 Port Royale

A casino game **strategy builder and simulator**. Define a betting strategy in
plain Python — including complicated, branching, stateful logic — then Monte
Carlo it over thousands of sessions to see its *realized* house edge, risk of
ruin, drawdown, and outcome distribution.

Starting with **craps** (full rule-correct engine). Designed so blackjack,
roulette, etc. slot in later.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Simulate 500 sessions of pass line + 5x odds, 10k rolls each
portroyale run --game craps --strategy passline_odds \
    --bankroll 1000 --rolls 10000 --sessions 500

# Reproducible run: master seed 7, stop at -50% / +100%
portroyale run --strategy passline_odds --seed 7 \
    --stop-loss 0.5 --stop-win 2.0 --sessions 200 --rolls 5000

# Watch ONE session play out roll by roll (same seed = same session)
portroyale watch --strategy passline_odds --seed 42 --rolls 300

# A/B strategies on IDENTICAL dice (common random numbers)
portroyale compare --strategies passline_odds,ironcross,dontpass_odds \
    --bankroll 1000 --rolls 5000 --sessions 100 --seed 7

# See every strategy and its tunable parameters
portroyale strategies

# Tune a strategy from the CLI
portroyale run --strategy ironcross --param base_unit=15 --param place_unit=18 \
    --bankroll 1000 --rolls 5000 --sessions 200

# Interactive lab with charts (Simulate tab) and roll-by-roll
# session playback (Watch tab)
streamlit run app.py
```

Example output:

```
Port Royale — craps / passline_odds
Sessions: 500   Rolls/session: 10000   Bankroll: $1,000.00
------------------------------------------------------------
Median final bankroll:  $        0.00
Mean net profit:        $     -136.06
Realized house edge:          0.27%  (per $ wagered)
Session win rate:             22.0%
Risk of ruin:                 72.6%
```

## Defining your own strategy

A strategy is a class with a `decide(table)` method, called before every
roll. Read the table state, branch on anything, and place bets directly:

```python
from portroyale.strategies.base import Strategy

class MyCrapsSystem(Strategy):
    name = "my_system"
    description = "Flat pass line, but press the 6/8 when we're ahead."
    PARAMS = {
        "base_unit": {"type": "float", "default": 10.0,
                      "label": "Base unit ($)", "help": "Pass line bet size."},
    }

    def decide(self, table):
        # Branch 1: the come-out — always get a pass line bet up.
        if table.phase == "comeout":
            if not table.has_bet("pass") and table.bankroll >= self.base_unit:
                table.place_bet("pass", self.base_unit)
            return

        # Branch 2: point is on — back it with odds ...
        if table.has_bet("pass") and not table.has_odds("pass"):
            table.add_odds("pass", min(50, table.bankroll))

        # Branch 3: ... and if we're playing with house money, press 6 and 8.
        if table.bankroll > table.starting_bankroll * 1.5:
            for n in (6, 8):
                if n != table.point and not table.has_bet("place", n):
                    table.place_bet("place", 12, n)
```

Strategies can also be **stateful**: keep counters on `self`, reset them in
`on_session_start`, and learn what just happened via
`table.drain_events()` (each event tells you which bet won/lost/pushed and
its profit). See `PressAfterWins` in
`src/portroyale/strategies/craps.py` — it doubles the unit after two
consecutive pass-line wins.

Register your class in `src/portroyale/strategies/__init__.py` (`STRATEGIES`
dict) and it appears in the CLI and the Streamlit app automatically — its
`PARAMS` become form fields / `--param` flags with zero extra code.

### The table API (craps)

| Method | What it does |
|---|---|
| `table.phase` / `table.point` | `"comeout"`/`"point"` and the point number |
| `table.bankroll` / `table.bets` | money left, live `Bet(kind, amount, number)` list |
| `table.place_bet(kind, amount, number=None)` | bet; enforces min/max, bankroll, placement rules |
| `table.add_odds(kind, amount, number=None)` | odds behind pass/don't/come/don't-come; enforces the odds multiple |
| `table.take_down(kind, number=None)` | remove a bet, refund the stake |
| `table.has_bet(kind, number=None)` / `table.has_odds(kind, number=None)` | inspect live bets |
| `table.drain_events()` | resolved-bet outcomes since last call (strategy memory) |
| `table.roll(d1=None, d2=None)` | resolve one roll (fixed dice for testing) |

Bet kinds: `pass`, `dontpass`, `come`, `dontcome`, `place`, `buy`, `lay`,
`hard`, `field`, `any_seven`, `any_craps`, `two_twelve`, `three_eleven`
(odds are added via `add_odds`, never placed directly).

## Seeds & replay

Every session is fully determined by its seed. `--seed N` on `run` sets a
*master* seed; session `i` plays the dice stream drawn from
`random.Random(N + i)`. Re-running with the same seed reproduces the run
exactly — same statistics, same sessions. The table engine itself takes a
`seed` too (`CrapsTable(seed=...)`), so dice always come from a per-table
`random.Random` instance.

## Watch mode

`portroyale watch` (or `streamlit run app.py` → **Watch** tab) plays a
single session and streams JSON-serializable events — `session_start`,
`bet_placed`, `bet_resolved`, `roll`, `bankroll`, `session_end` — one per
roll. Same seed always replays the identical session. This stream is the
cross-platform contract the future mobile table will render; the schema
is documented in `docs/watch-mode.md`.

## Comparing strategies (common random numbers)

`portroyale compare` runs several strategies against the **identical**
dice: each session's dice are generated once from the seed and replayed
for every strategy. Shared randomness cancels out most of the luck, so
differences in the results are differences in the strategies, not the
dice. (A seed is required — without shared dice a comparison would just
measure noise.) Output is a side-by-side table: realized edge, win rate,
ruin rate, drawdown, median/p5/p95 final bankroll, and the session-end
breakdown per strategy.

## Stop-loss / stop-win

Sessions can end early: `--stop-loss 0.5` stops a session at ≤50% of the
starting bankroll, `--stop-win 2.0` at ≥200%. Reports show what fraction
of sessions ended by each reason (`rolls_exhausted`, `ruin`,
`stop_loss`, `stop_win`).

## Project layout

```
app.py                          Streamlit strategy lab (charts + forms)
docs/
    mobile-roadmap.md           iOS/Android target architecture + guardrails
    watch-mode.md               watch-mode event schema (cross-platform contract)
src/portroyale/
    games/base.py               Table/Bet/BetEvent primitives shared by all games
    games/craps.py              Rule-correct craps engine (true-odds payouts,
                                bar-12, hardways, come-bet travel, table limits)
    strategies/base.py          Strategy framework (decide/table API)
    strategies/craps.py         passline_odds, dontpass_odds, ironcross, presser
    sim.py                      Monte Carlo engine: run_simulation, watch_session
                                (per-roll event stream), run_comparison
                                (common-random-numbers A/B), stop controls
    cli.py                      `portroyale run` / `watch` / `compare` / `strategies`
tests/                          61 pytest tests incl. exact-payout rule tests,
                                determinism (same seed -> identical streams),
                                compare-mode dice fairness, stop triggers,
                                and JSON-serializability of every event
```

## How the simulation works

One **session** = start with a bankroll, loop `decide → roll` for N rolls
(or until the bankroll can't cover the table minimum — that's a ruin — or a
stop-loss/stop-win level is hit). `run_simulation` repeats this for M
sessions across all CPU cores and
reports: realized house edge (−profit ÷ total wagered), session win rate,
risk of ruin, max drawdown, final-bankroll percentiles, percentile
bands of bankroll over time, and the fraction of sessions ended by each
reason (rolls exhausted / ruin / stop-loss / stop-win).

## Adding a new game

1. New module in `src/portroyale/games/` subclassing `Table` (implement
   `roll()` + bet placement; reuse `Bet`, `_charge`, `_settle`,
   `drain_events`).
2. One line in `src/portroyale/games/__init__.py` (`GAMES` dict).
3. Strategies in `src/portroyale/strategies/`. The sim loop only assumes
   `decide(table)` + `table.roll()`, so it works unchanged.

## Testing

```bash
pytest            # 61 tests: come-out naturals/craps, point play, true-odds
                  # payouts per number, bar-12, place/buy/field/hardway math,
                  # come-bet travel, table limits, sim smoke tests,
                  # seed determinism, watch-stream schema + JSON checks,
                  # compare-mode dice fairness, stop-loss/stop-win triggers
```

## Roadmap

- **Mobile apps (iOS + Android):** target is a React Native + TypeScript app;
  the Python engine is the reference spec. See `docs/mobile-roadmap.md` for the
  target architecture and guardrails. Until the port starts: keep the engine
  UI-free, no Python-only strategy features, limit Streamlit investment.
- Blackjack engine (basic-strategy + counting strategies)
- Roulette engine
- Strategy comparison mode (A/B multiple strategies in one run)
- Session bankroll charts export

## Disclaimer

For education and entertainment. The math here will confirm what the math
always confirms: no betting system overcomes the house edge. That's rather
the point of the simulator.
