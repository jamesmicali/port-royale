/**
 * Monte Carlo simulation engine.
 *
 * Concept-for-concept port of `sim.py`. A *session* is one run of a
 * strategy: start with a bankroll, let the strategy bet before every
 * round, resolve the round, and repeat for `rolls` rounds (or until the
 * bankroll can no longer cover the table minimum — that's a ruin).
 *
 * Reproducibility: every session is fully determined by its seed. The
 * master seed plus the session index derives the session seed
 * (`master + index`), exactly like the Python engine. Note the dice
 * *values* differ from Python for the same seed (different PRNG — see
 * `prng.ts`); determinism is per-platform.
 *
 * Watch mode: `watchSession` plays a single session and yields the
 * JSON-serializable event stream defined in `events.ts` (the
 * cross-platform contract — see `docs/watch-mode.md`). `runSession` is
 * built on the same generator, so simulated statistics and the visible
 * play-by-play can never disagree.
 *
 * Comparison mode: `runComparison` runs several strategies against the
 * *identical* dice streams (common random numbers).
 *
 * UI-free: no React / React Native imports.
 */

import { CrapsTable } from "./craps";
import {
  BankrollEvent,
  BetPlacedEvent,
  BetResolvedEvent,
  RollEvent,
  SessionEndEvent,
  SessionEndReason,
  SessionStartEvent,
  WatchEvent,
} from "./events";
import { SeededRng } from "./prng";
import { makeStrategy } from "./strategies";
import { Bet, BetEvent, TableError } from "./table";

export const HISTORY_POINTS = 400; // bankroll samples kept per session

export const REASON_EXHAUSTED = "rolls_exhausted" as const;
export const REASON_RUIN = "ruin" as const;
export const REASON_STOP_LOSS = "stop_loss" as const;
export const REASON_STOP_WIN = "stop_win" as const;
export const REASON_ERROR = "error" as const;

export interface TableConfig {
  minBet: number;
  maxBet: number;
  oddsMultiple: number;
}

export const DEFAULT_TABLE_CONFIG: TableConfig = {
  minBet: 5.0,
  maxBet: 5000.0,
  oddsMultiple: 5,
};

/** Derive a session's seed deterministically from the master seed. */
export function sessionSeed(
  masterSeed: number | null | undefined,
  sessionIndex: number
): number | null {
  return masterSeed == null ? null : masterSeed + sessionIndex;
}

/** Generate `n` dice pairs from `seed`. Shared by sim and compare. */
export function makeDiceStream(seed: number, n: number): Array<[number, number]> {
  const rng = new SeededRng(seed);
  const out: Array<[number, number]> = [];
  for (let i = 0; i < n; i++) out.push([rng.die(), rng.die()]);
  return out;
}

/* ------------------------------------------------------------------ */
/* Session event generator (the single source of truth)                */
/* ------------------------------------------------------------------ */

export interface WatchOptions {
  game?: string;
  strategy?: string;
  strategyParams?: Record<string, unknown>;
  bankroll?: number;
  minBet?: number;
  maxBet?: number;
  oddsMultiple?: number;
  rolls?: number;
  seed?: number | null;
  stopLoss?: number | null; // end session at <= this fraction of start
  stopWin?: number | null; // end session at >= this fraction of start
  dice?: Array<[number, number]> | null;
}

function betPlacedEvent(rollNo: number, bet: Bet): BetPlacedEvent {
  return {
    type: "bet_placed",
    roll: rollNo,
    kind: bet.kind,
    amount: bet.amount,
    number: bet.number,
  };
}

function betResolvedEvent(rollNo: number, event: BetEvent): BetResolvedEvent {
  return {
    type: "bet_resolved",
    roll: rollNo,
    kind: event.kind,
    number: event.number,
    amount: event.amount,
    outcome: event.outcome,
    profit: event.profit,
  };
}

function makeTable(
  game: string,
  opts: {
    bankroll: number;
    minBet: number;
    maxBet: number;
    oddsMultiple: number;
  }
): CrapsTable {
  if (game !== "craps") {
    throw new Error(`unknown game ${JSON.stringify(game)}; available: ["craps"]`);
  }
  return new CrapsTable(opts);
}

/**
 * Play one session, yielding JSON-serializable event dicts.
 *
 * Per-roll ordering (the contract): bet_placed × N, bet_resolved × M
 * (take-downs during decide), roll, bet_resolved × K (settlements),
 * bankroll.
 */
export function* watchSession(
  opts: WatchOptions = {},
  sessionIndex = 0,
  dice: Array<[number, number]> | null = null
): Generator<WatchEvent> {
  const game = opts.game ?? "craps";
  const strategyName = opts.strategy ?? "passline_odds";
  const strategyParams = { ...(opts.strategyParams ?? {}) };
  const bankroll = opts.bankroll ?? 1000.0;
  const minBet = opts.minBet ?? DEFAULT_TABLE_CONFIG.minBet;
  const maxBet = opts.maxBet ?? DEFAULT_TABLE_CONFIG.maxBet;
  const oddsMultiple = opts.oddsMultiple ?? DEFAULT_TABLE_CONFIG.oddsMultiple;
  const rolls = opts.rolls ?? 300;
  const masterSeed = opts.seed ?? 42;
  const stopLoss = opts.stopLoss ?? null;
  const stopWin = opts.stopWin ?? null;

  if (stopLoss != null && stopLoss <= 0) {
    throw new Error(`stopLoss must be positive, got ${stopLoss}`);
  }
  if (stopWin != null && stopWin <= 0) {
    throw new Error(`stopWin must be positive, got ${stopWin}`);
  }

  const seed = sessionSeed(masterSeed, sessionIndex);
  const explicitDice = opts.dice ?? dice;
  const stream =
    explicitDice ?? (seed != null ? makeDiceStream(seed, rolls) : null);

  const table = makeTable(game, { bankroll, minBet, maxBet, oddsMultiple });
  const strategy = makeStrategy(strategyName, strategyParams);
  strategy.onSessionStart(table);

  const start = bankroll;

  const startEvent: SessionStartEvent = {
    type: "session_start",
    game,
    strategy: strategyName,
    strategy_params: strategyParams,
    seed,
    bankroll: start,
    rolls,
    stop_loss: stopLoss,
    stop_win: stopWin,
    min_bet: minBet,
    max_bet: maxBet,
    odds_multiple: Math.trunc(oddsMultiple),
  };
  yield startEvent;

  let peak = start;
  let maxDD = 0;
  let rollsPlayed = 0;
  let reason: SessionEndReason = REASON_EXHAUSTED;
  let error: string | undefined;

  for (let r = 1; r <= rolls; r++) {
    if (table.bankroll < table.minBet - 1e-9) {
      reason = REASON_RUIN;
      break;
    }
    const known = new Set<Bet>(table.bets);
    try {
      strategy.decide(table);
    } catch (e) {
      if (e instanceof TableError) {
        reason = REASON_ERROR;
        error = e.message;
        break;
      }
      throw e;
    }
    for (const bet of table.bets) {
      if (!known.has(bet)) yield betPlacedEvent(r, bet);
    }
    for (const event of table.drainEvents()) {
      // take-downs / adjustments during decide()
      yield betResolvedEvent(r, event);
    }

    let d1: number;
    let d2: number;
    if (stream) {
      [d1, d2] = stream[r - 1];
      table.roll(d1, d2);
    } else {
      const result = table.roll();
      d1 = result.d1;
      d2 = result.d2;
    }
    const rollEvent: RollEvent = {
      type: "roll",
      roll: r,
      d1,
      d2,
      total: d1 + d2,
      phase: table.phase, // phase *after* the roll resolved
      point: table.point, // point *after* the roll resolved
    };
    yield rollEvent;
    for (const event of table.drainEvents()) {
      yield betResolvedEvent(r, event);
    }

    rollsPlayed = r;
    peak = Math.max(peak, table.bankroll);
    maxDD = Math.max(maxDD, peak - table.bankroll);
    const bankrollEvent: BankrollEvent = {
      type: "bankroll",
      roll: r,
      bankroll: table.bankroll,
    };
    yield bankrollEvent;

    if (stopWin != null && table.bankroll >= stopWin * start - 1e-9) {
      reason = REASON_STOP_WIN;
      break;
    }
    if (stopLoss != null && table.bankroll <= stopLoss * start + 1e-9) {
      reason = REASON_STOP_LOSS;
      break;
    }
  }

  const endEvent: SessionEndEvent = {
    type: "session_end",
    reason,
    rolls_played: rollsPlayed,
    final_bankroll: table.bankroll,
    net_profit: table.bankroll - start,
    total_wagered: table.totalWagered,
    max_drawdown: maxDD,
  };
  if (error !== undefined) endEvent.error = error;
  yield endEvent;
}

/* ------------------------------------------------------------------ */
/* Session results                                                     */
/* ------------------------------------------------------------------ */

export interface SessionResult {
  finalBankroll: number;
  profit: number;
  action: number; // total dollars wagered
  edge: number; // realized house edge for this session (-profit/action)
  maxDrawdown: number;
  ruined: boolean;
  rollsPlayed: number;
  endReason: SessionEndReason;
  seed: number | null;
  history: number[]; // downsampled bankroll trajectory
}

/**
 * Run one session, consuming the same event generator as `watchSession`
 * so simulated statistics and the visible play-by-play always agree.
 */
export function runSession(
  cfg: Required<SimConfig>,
  sessionIndex: number,
  dice: Array<[number, number]> | null = null
): SessionResult {
  const seed = sessionSeed(cfg.seed, sessionIndex);
  const start = cfg.bankroll;
  // Sample at most HISTORY_POINTS points; pad short runs to equal length.
  const step = Math.max(1, Math.ceil(cfg.rolls / HISTORY_POINTS));
  const history: number[] = [start];
  let endReason: SessionEndReason = REASON_EXHAUSTED;
  let final = start;
  let profit = 0;
  let action = 0;
  let maxDD = 0;
  let rollsPlayed = 0;

  for (const event of watchSession(
    {
      game: cfg.game,
      strategy: cfg.strategy,
      strategyParams: cfg.strategyParams,
      bankroll: cfg.bankroll,
      minBet: cfg.table.minBet,
      maxBet: cfg.table.maxBet,
      oddsMultiple: cfg.table.oddsMultiple,
      rolls: cfg.rolls,
      seed: cfg.seed,
      stopLoss: cfg.stopLoss,
      stopWin: cfg.stopWin,
    },
    sessionIndex,
    dice
  )) {
    if (event.type === "bankroll") {
      const r = event.roll;
      if (r % step === 0 || r === cfg.rolls) history.push(event.bankroll);
    } else if (event.type === "session_end") {
      endReason = event.reason;
      final = event.final_bankroll;
      profit = event.net_profit;
      action = event.total_wagered;
      maxDD = event.max_drawdown;
      rollsPlayed = event.rolls_played;
      if (rollsPlayed % step !== 0) history.push(final);
    }
  }

  // Pad the trajectory so every session lines up for percentile bands.
  while (history.length < HISTORY_POINTS + 1) {
    history.push(history[history.length - 1]);
  }

  const edge = action > 0 ? -profit / action : 0;
  return {
    finalBankroll: final,
    profit,
    action,
    edge,
    maxDrawdown: maxDD,
    ruined: endReason === REASON_RUIN,
    rollsPlayed,
    endReason,
    seed,
    history,
  };
}

/* ------------------------------------------------------------------ */
/* Statistics                                                          */
/* ------------------------------------------------------------------ */

/** Percentile with linear interpolation — matches numpy.percentile default. */
export function percentile(sorted: number[], q: number): number {
  if (sorted.length === 0) return NaN;
  if (sorted.length === 1) return sorted[0];
  const pos = (q / 100) * (sorted.length - 1);
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function quantile(values: number[], q: number): number {
  return percentile([...values].sort((a, b) => a - b), q);
}

function mean(values: number[]): number {
  return values.reduce((s, v) => s + v, 0) / Math.max(1, values.length);
}

export interface SimReport {
  sessions: number;
  meanFinal: number;
  medianFinal: number;
  p5Final: number;
  p25Final: number;
  p75Final: number;
  p95Final: number;
  meanProfit: number;
  totalAction: number;
  /** -totalProfit / totalAction */
  realizedEdge: number;
  /** fraction of sessions finishing above start */
  winRate: number;
  /** fraction of sessions ruined */
  ruinRate: number;
  meanMaxDrawdown: number;
  medianRollsPlayed: number;
  /** reason -> fraction of sessions */
  endReasons: Record<string, number>;
  /** p5/p25/p50/p75/p95 bankroll over time */
  bands: Record<string, number[]>;
}

export interface SimConfig {
  game?: string;
  strategy?: string;
  strategyParams?: Record<string, unknown>;
  bankroll?: number;
  table?: Partial<TableConfig>;
  rolls?: number;
  sessions?: number;
  seed?: number | null;
  stopLoss?: number | null;
  stopWin?: number | null;
}

function normalizeConfig(cfg: SimConfig): Required<SimConfig> {
  const table: TableConfig = {
    ...DEFAULT_TABLE_CONFIG,
    ...(cfg.table ?? {}),
  };
  return {
    game: cfg.game ?? "craps",
    strategy: cfg.strategy ?? "passline_odds",
    strategyParams: cfg.strategyParams ?? {},
    bankroll: cfg.bankroll ?? 1000.0,
    table,
    rolls: cfg.rolls ?? 10000,
    sessions: cfg.sessions ?? 500,
    seed: cfg.seed ?? null,
    stopLoss: cfg.stopLoss ?? null,
    stopWin: cfg.stopWin ?? null,
  };
}

function aggregate(
  results: SessionResult[],
  config: Required<SimConfig>
): SimReport {
  const finals = results.map((r) => r.finalBankroll);
  const profits = results.map((r) => r.profit);
  const actions = results.map((r) => r.action);

  const totalProfit = profits.reduce((s, v) => s + v, 0);
  const totalAction = actions.reduce((s, v) => s + v, 0);

  const bands: Record<string, number[]> = {};
  for (const [name, q] of [
    ["p5", 5],
    ["p25", 25],
    ["p50", 50],
    ["p75", 75],
    ["p95", 95],
  ] as Array<[string, number]>) {
    const series: number[] = [];
    const points = results[0]?.history.length ?? 0;
    for (let i = 0; i < points; i++) {
      series.push(quantile(results.map((r) => r.history[i]), q));
    }
    bands[name] = series;
  }

  const endReasons: Record<string, number> = {};
  for (const r of results) {
    endReasons[r.endReason] = (endReasons[r.endReason] ?? 0) + 1;
  }
  const n = Math.max(1, results.length);
  for (const k of Object.keys(endReasons)) endReasons[k] /= n;

  return {
    sessions: results.length,
    meanFinal: mean(finals),
    medianFinal: quantile(finals, 50),
    p5Final: quantile(finals, 5),
    p25Final: quantile(finals, 25),
    p75Final: quantile(finals, 75),
    p95Final: quantile(finals, 95),
    meanProfit: mean(profits),
    totalAction,
    realizedEdge: totalAction > 0 ? -totalProfit / totalAction : 0,
    winRate: mean(finals.map((f) => (f > config.bankroll ? 1 : 0))),
    ruinRate: mean(results.map((r) => (r.ruined ? 1 : 0))),
    meanMaxDrawdown: mean(results.map((r) => r.maxDrawdown)),
    medianRollsPlayed: quantile(
      results.map((r) => r.rollsPlayed),
      50
    ),
    endReasons,
    bands,
  };
}

/** Run `sessions` sessions (synchronously) and aggregate into a report. */
export function runSimulation(config: SimConfig): SimReport {
  const cfg = normalizeConfig(config);
  const results: SessionResult[] = [];
  for (let i = 0; i < cfg.sessions; i++) {
    results.push(runSession(cfg, i));
  }
  return aggregate(results, cfg);
}

/* ------------------------------------------------------------------ */
/* Comparison mode (common random numbers)                             */
/* ------------------------------------------------------------------ */

export interface ComparisonReport {
  game: string;
  strategies: string[];
  sessions: number;
  rolls: number;
  bankroll: number;
  seed: number;
  reports: Record<string, SimReport>;
}

/**
 * Run several strategies against IDENTICAL dice streams.
 *
 * For session `i` the dice are generated once from `seed + i` and replayed
 * for every strategy — common random numbers, so result differences
 * reflect strategy differences, not luck. A seed is required.
 */
export function runComparison(opts: {
  game?: string;
  strategies: string[];
  strategyParams?: Record<string, Record<string, unknown>>;
  bankroll?: number;
  table?: Partial<TableConfig>;
  rolls?: number;
  sessions?: number;
  seed: number | null;
  stopLoss?: number | null;
  stopWin?: number | null;
}): ComparisonReport {
  const {
    game = "craps",
    strategies,
    strategyParams = {},
    bankroll = 1000.0,
    table,
    rolls = 5000,
    sessions = 100,
    seed,
    stopLoss = null,
    stopWin = null,
  } = opts;

  if (seed == null) {
    throw new Error(
      "compare requires a seed — identical dice are the whole point"
    );
  }
  if (strategies.length < 2) {
    throw new Error("compare needs at least two strategies");
  }

  const reports: Record<string, SimReport> = {};
  for (const name of strategies) {
    const cfg = normalizeConfig({
      game,
      strategy: name,
      strategyParams: strategyParams[name] ?? {},
      bankroll,
      table,
      rolls,
      sessions,
      seed,
      stopLoss,
      stopWin,
    });
    const results: SessionResult[] = [];
    for (let i = 0; i < sessions; i++) {
      const dice = makeDiceStream(seed + i, rolls);
      results.push(runSession(cfg, i, dice));
    }
    reports[name] = aggregate(results, cfg);
  }

  return { game, strategies, sessions, rolls, bankroll, seed, reports };
}
