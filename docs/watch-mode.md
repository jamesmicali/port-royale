# Watch mode — event stream contract

`portroyale.sim.watch_session(...)` plays a single session and yields a
stream of **plain-JSON event dicts** — no Python objects, every value a
`str`, `int`, `float`, `bool`, `None`, or a dict/list of those
(`json.dumps` must succeed on every event; there is a test for this).

This stream is a **cross-platform contract**: it is what the future React
Native craps table consumes to animate a session (dice tumbles, chips
moving, win highlights). Any producer — Python today, TypeScript tomorrow —
must emit these exact event types and fields so viewers stay compatible.

## Producing the stream

```python
from portroyale.sim import watch_session

for event in watch_session(game="craps", strategy="passline_odds",
                           seed=42, bankroll=1000.0, rolls=300):
    ...  # event is a JSON-serializable dict
```

The simulator (`run_session`) consumes the *same* generator, so simulated
statistics and the visible play-by-play can never disagree.

## Replay

A session is fully determined by `(game, strategy, strategy_params,
seed, bankroll, rolls, stop_loss, stop_win, table config)`. Same inputs →
byte-identical event stream. Dice for session `i` of a seeded run come
from `random.Random(master_seed + i)`.

## Event types

Every event has a `"type"` field. `roll` is the per-roll sequence number
(1-based).

### `session_start`

```json
{"type": "session_start", "game": "craps", "strategy": "passline_odds",
 "strategy_params": {"base_unit": 10.0}, "seed": 42,
 "bankroll": 1000.0, "rolls": 300,
 "stop_loss": null, "stop_win": null,
 "min_bet": 5.0, "max_bet": 5000.0, "odds_multiple": 5}
```

### `bet_placed`

Emitted for every bet the strategy places before the roll (flat bets and
odds alike).

```json
{"type": "bet_placed", "roll": 12, "kind": "pass",
 "amount": 10.0, "number": null}
```

`number` is the box number for bets that need one (`place`, `hard`, odds…),
else `null`.

### `bet_resolved`

Emitted for every bet that resolves — after the roll, plus any bets the
strategy took down during `decide()` (those carry `"outcome": "returned"`).

```json
{"type": "bet_resolved", "roll": 12, "kind": "pass",
 "number": null, "amount": 10.0, "outcome": "won", "profit": 10.0}
```

`outcome` ∈ `won` | `lost` | `push` | `returned` | `travel`.
`profit` is net profit to the player (negative on a loss, `0.0` on
push/return/travel). `travel` means a come/don't-come bet moved to a box
number — the bet is still live, no money moved.

### `roll`

The dice. `phase`/`point` describe the table **after** the roll resolved.

```json
{"type": "roll", "roll": 12, "d1": 3, "d2": 3, "total": 6,
 "phase": "point", "point": 6}
```

`phase` ∈ `comeout` | `point`; `point` is `null` on come-out rolls.

### `bankroll`

Per-roll bankroll snapshot, emitted after all resolutions.

```json
{"type": "bankroll", "roll": 12, "bankroll": 1024.0}
```

### `session_end`

Always the last event.

```json
{"type": "session_end", "reason": "stop_win", "rolls_played": 87,
 "final_bankroll": 2030.0, "net_profit": 1030.0,
 "total_wagered": 15240.0, "max_drawdown": 410.0}
```

`reason` ∈ `rolls_exhausted` | `ruin` | `stop_loss` | `stop_win` | `error`.
When `reason` is `error`, an extra `"error"` string field carries the
message (a strategy bug or broken table invariant — not a normal outcome).

## Per-roll ordering

For each roll, events arrive in this order:

1. `bet_placed` × N (strategy's bets for this roll)
2. `bet_resolved` × M (take-downs during `decide()`, if any)
3. `roll` (the dice)
4. `bet_resolved` × K (everything the roll settled)
5. `bankroll` (snapshot)

## Notes for the TypeScript port

- Reproduce this schema exactly: same type names, same field names.
- The seeded dice source is `random.Random(seed)` per session; the TS port
  should use a deterministic PRNG keyed the same way (`seed + session_index`).
  Shared test vectors (fixed dice → expected event stream) will verify the
  port.
- Viewers should treat unknown future fields as ignorable, but the six
  types above are the stable contract.
