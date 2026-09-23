/**
 * Watch-mode stream + sim-loop tests for the TypeScript engine.
 *
 * Pins down the cross-platform contract from docs/watch-mode.md:
 * determinism (same seed -> identical streams), the exact event schema,
 * per-roll ordering, JSON-serializability, and bankroll accounting.
 */
import {
  SessionEndEvent,
  WatchEvent,
  WATCH_EVENT_TYPES,
} from "../events";
import {
  makeDiceStream,
  percentile,
  runComparison,
  runSession,
  runSimulation,
  sessionSeed,
  watchSession,
  type SimConfig,
} from "../sim";

const STRATEGIES = ["passline_odds", "dontpass_odds", "ironcross"] as const;

/* ------------------------------------------------- seeded determinism */

test("same seed => identical event streams", () => {
  const a = [...watchSession({ seed: 42, rolls: 100 })];
  const b = [...watchSession({ seed: 42, rolls: 100 })];
  expect(a).toEqual(b);
  expect(a[0].type).toBe("session_start");
  expect(a[a.length - 1].type).toBe("session_end");
});

test("different seeds => different streams", () => {
  const a = [...watchSession({ seed: 42, rolls: 100 })];
  const b = [...watchSession({ seed: 43, rolls: 100 })];
  expect(a).not.toEqual(b);
});

test("session seed derives from master seed + index", () => {
  expect(sessionSeed(7, 0)).toBe(7);
  expect(sessionSeed(7, 3)).toBe(10);
  expect(sessionSeed(null, 3)).toBeNull();
});

test("makeDiceStream is stable per seed", () => {
  expect(makeDiceStream(7, 100)).toEqual(makeDiceStream(7, 100));
  expect(makeDiceStream(7, 50)).not.toEqual(makeDiceStream(8, 50));
});

test("same seed => identical sim results", () => {
  const kw: SimConfig = {
    strategy: "passline_odds",
    bankroll: 1000,
    rolls: 500,
    sessions: 8,
    seed: 42,
  };
  const r1 = runSimulation(kw);
  const r2 = runSimulation(kw);
  expect(r1.realizedEdge).toBe(r2.realizedEdge);
  expect(r1.medianFinal).toBe(r2.medianFinal);
  expect(r1.meanFinal).toBe(r2.meanFinal);
  expect(r1.endReasons).toEqual(r2.endReasons);
});

/* ------------------------------------------------------- schema parity */

/** Exact field sets from docs/watch-mode.md (session_end may add `error`). */
const SCHEMA: Record<string, string[]> = {
  session_start: [
    "type",
    "game",
    "strategy",
    "strategy_params",
    "seed",
    "bankroll",
    "rolls",
    "stop_loss",
    "stop_win",
    "min_bet",
    "max_bet",
    "odds_multiple",
  ],
  bet_placed: ["type", "roll", "kind", "amount", "number"],
  bet_resolved: [
    "type",
    "roll",
    "kind",
    "number",
    "amount",
    "outcome",
    "profit",
  ],
  roll: ["type", "roll", "d1", "d2", "total", "phase", "point"],
  bankroll: ["type", "roll", "bankroll"],
  session_end: [
    "type",
    "reason",
    "rolls_played",
    "final_bankroll",
    "net_profit",
    "total_wagered",
    "max_drawdown",
  ],
};

test("every event matches the documented schema exactly", () => {
  for (const strategy of STRATEGIES) {
    const events = [...watchSession({ strategy, seed: 99, rolls: 200 })];
    expect(events.length).toBeGreaterThan(200);
    const types = new Set(events.map((e) => e.type));
    for (const t of ["session_start", "roll", "bankroll", "session_end"]) {
      expect(types).toContain(t);
    }
    for (const e of events) {
      expect(WATCH_EVENT_TYPES).toContain(e.type);
      const keys = new Set(Object.keys(e));
      const expected = new Set(SCHEMA[e.type]);
      if (e.type === "session_end" && "error" in e) expected.add("error");
      expect(keys).toEqual(expected);
    }
  }
});

test("every event is JSON-serializable and round-trips", () => {
  const events = [...watchSession({ seed: 42, rolls: 50 })];
  for (const e of events) {
    const json = JSON.stringify(e); // must not throw
    expect(JSON.parse(json)).toEqual(e);
  }
});

test("per-roll ordering: placed, takedowns, roll, settlements, bankroll", () => {
  const events = [...watchSession({ strategy: "ironcross", seed: 7, rolls: 60 })];
  expect(events[0].type).toBe("session_start");
  expect(events[events.length - 1].type).toBe("session_end");

  const byRoll = new Map<number, string[]>();
  for (const e of events) {
    if (e.type === "session_start" || e.type === "session_end") continue;
    const roll = (e as { roll: number }).roll;
    const arr = byRoll.get(roll) ?? [];
    arr.push(e.type);
    byRoll.set(roll, arr);
  }
  for (const [roll, types] of byRoll) {
    const rollIdx = types.indexOf("roll");
    expect(rollIdx).toBeGreaterThanOrEqual(0);
    // exactly one roll event and one bankroll event, bankroll last
    expect(types.filter((t) => t === "roll")).toHaveLength(1);
    expect(types.filter((t) => t === "bankroll")).toHaveLength(1);
    expect(types[types.length - 1]).toBe("bankroll");
    // before the dice: only placements and decide-time take-downs
    for (let i = 0; i < rollIdx; i++) {
      expect(["bet_placed", "bet_resolved"]).toContain(types[i]);
    }
    // after the dice, before the bankroll snapshot: only settlements
    for (let i = rollIdx + 1; i < types.length - 1; i++) {
      expect(types[i]).toBe("bet_resolved");
    }
  }
});

test("roll events carry dice and post-roll table state", () => {
  const events = [...watchSession({ seed: 42, rolls: 10 })];
  const rolls = events.filter((e) => e.type === "roll");
  expect(rolls).toHaveLength(10);
  for (const e of rolls) {
    if (e.type !== "roll") continue;
    expect(e.d1).toBeGreaterThanOrEqual(1);
    expect(e.d1).toBeLessThanOrEqual(6);
    expect(e.total).toBe(e.d1 + e.d2);
    expect(["comeout", "point"]).toContain(e.phase);
  }
});

test("bet_placed and bet_resolved events line up", () => {
  const events = [
    ...watchSession({ strategy: "passline_odds", seed: 42, rolls: 30 }),
  ];
  const placed = events.filter((e) => e.type === "bet_placed");
  const resolved = events.filter((e) => e.type === "bet_resolved");
  expect(placed.length).toBeGreaterThan(0);
  expect(resolved.length).toBeGreaterThan(0);
  for (const e of resolved) {
    if (e.type !== "bet_resolved") continue;
    expect(["won", "lost", "push", "returned", "travel"]).toContain(e.outcome);
  }
});

/* ------------------------------------------------- money accounting */

test("bankroll reconciles with resolved profits and live stakes", () => {
  for (const strategy of STRATEGIES) {
    for (const seed of [7, 99]) {
      const events = [...watchSession({ strategy, seed, rolls: 200 })];
      const start = (events[0] as { bankroll: number }).bankroll;
      let liveStakes = 0;
      let resolvedProfit = 0;
      for (const e of events) {
        if (e.type === "bet_placed") {
          liveStakes += e.amount;
        } else if (e.type === "bet_resolved") {
          if (e.outcome === "travel") continue; // bet stays live
          liveStakes -= e.amount;
          resolvedProfit += e.profit;
        }
      }
      const end = events[events.length - 1] as SessionEndEvent;
      expect(end.type).toBe("session_end");
      // final = start + Σ(resolved profits) − stakes still on the table
      expect(
        Math.abs(end.final_bankroll - (start + resolvedProfit - liveStakes))
      ).toBeLessThan(1e-6);
      expect(end.net_profit).toBeCloseTo(end.final_bankroll - start, 9);
    }
  }
});

/* ------------------------------------------------------- stop control */

test("stop_loss triggers on a bleeding dice stream", () => {
  const dice: Array<[number, number]> = Array(300).fill([1, 1]); // craps every come-out
  const events = [
    ...watchSession({
      strategy: "passline_odds",
      seed: 1,
      bankroll: 1000,
      rolls: 300,
      stopLoss: 0.5,
      dice,
    }),
  ];
  const end = events[events.length - 1] as SessionEndEvent;
  expect(end.type).toBe("session_end");
  expect(end.reason).toBe("stop_loss");
  expect(end.rolls_played).toBe(50);
  expect(end.final_bankroll).toBeCloseTo(500, 9);
});

test("stop_win triggers on a winning dice stream", () => {
  const dice: Array<[number, number]> = Array(300).fill([3, 4]); // natural every come-out
  const events = [
    ...watchSession({
      strategy: "passline_odds",
      seed: 1,
      bankroll: 1000,
      rolls: 300,
      stopWin: 2.0,
      dice,
    }),
  ];
  const end = events[events.length - 1] as SessionEndEvent;
  expect(end.reason).toBe("stop_win");
  expect(end.final_bankroll).toBeGreaterThanOrEqual(2000 - 1e-9);
});

test("ruin ends the session when the bankroll can't cover the minimum", () => {
  const dice: Array<[number, number]> = Array(300).fill([1, 1]);
  const events = [
    ...watchSession({
      strategy: "passline_odds",
      seed: 1,
      bankroll: 100,
      rolls: 300,
      dice,
    }),
  ];
  const end = events[events.length - 1] as SessionEndEvent;
  expect(end.reason).toBe("ruin");
});

test("bad stop values are rejected", () => {
  expect(() =>
    [...watchSession({ stopLoss: 0 })].length
  ).toThrow();
  expect(() =>
    [...watchSession({ stopWin: -1 })].length
  ).toThrow();
});

/* ------------------------------------------------------------ compare */

test("compare requires a seed and at least two strategies", () => {
  expect(() =>
    runComparison({ strategies: ["passline_odds", "ironcross"], seed: null })
  ).toThrow();
  expect(() =>
    runComparison({ strategies: ["passline_odds"], seed: 7 })
  ).toThrow();
});

test("compare runs strategies on identical dice and reports sanely", () => {
  const report = runComparison({
    strategies: ["passline_odds", "ironcross"],
    sessions: 4,
    rolls: 200,
    bankroll: 1000,
    seed: 7,
  });
  expect(report.sessions).toBe(4);
  for (const name of ["passline_odds", "ironcross"]) {
    const r = report.reports[name];
    expect(r.sessions).toBe(4);
    expect(Number.isFinite(r.realizedEdge)).toBe(true);
    expect(r.bands.p50).toHaveLength(401); // HISTORY_POINTS + 1
  }
});

/* -------------------------------------------------------------- stats */

test("percentile uses linear interpolation like numpy", () => {
  expect(percentile([1, 2, 3, 4], 50)).toBeCloseTo(2.5, 12);
  expect(percentile([1, 2, 3, 4], 0)).toBe(1);
  expect(percentile([1, 2, 3, 4], 100)).toBe(4);
});

test("runSession history is padded to HISTORY_POINTS + 1", () => {
  const cfg = {
    game: "craps",
    strategy: "passline_odds",
    strategyParams: {},
    bankroll: 1000,
    table: { minBet: 5, maxBet: 5000, oddsMultiple: 5 },
    rolls: 50,
    sessions: 1,
    seed: 42,
    stopLoss: null,
    stopWin: null,
  };
  const r = runSession(cfg, 0);
  expect(r.history).toHaveLength(401);
  expect(r.seed).toBe(42);
  expect(r.endReason).toBe("rolls_exhausted");
});

test("strategy rejects unknown params", () => {
  expect(() =>
    [...watchSession({ strategy: "passline_odds", strategyParams: { nope: 1 } })]
  ).toThrow();
});

test("unknown strategy is rejected", () => {
  expect(() => [...watchSession({ strategy: "martingale" })]).toThrow();
});
