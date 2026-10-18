/**
 * Shared base classes for casino game tables.
 *
 * Every game in Port Royale exposes a *table* object with the same small
 * interface so the strategy framework and the Monte Carlo engine can drive
 * any game without knowing its rules:
 *
 * - `table.bankroll` / `table.bets` — observable state
 * - `strategy.decide(table)` — the strategy places / removes bets
 * - `table.roll()` — the game resolves one round and settles all bets
 * - `table.drainEvents()` — resolved-bet outcomes since the last call,
 *   which stateful strategies use as memory
 *
 * This is a concept-for-concept port of `games/base.py`. It is UI-free:
 * no React, no React Native imports anywhere in this directory.
 */

import { SeededRng } from "./prng";

/* ------------------------------------------------------------------ */
/* Errors                                                              */
/* ------------------------------------------------------------------ */

export class TableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TableError";
  }
}

/** Raised when a bet costs more than the current bankroll. */
export class InsufficientBankroll extends TableError {
  constructor(message: string) {
    super(message);
    this.name = "InsufficientBankroll";
  }
}

/** Raised when a bet violates min/max limits or placement rules. */
export class TableLimitError extends TableError {
  constructor(message: string) {
    super(message);
    this.name = "TableLimitError";
  }
}

/** Raised when a bet kind is not recognised by the game. */
export class UnknownBetError extends TableError {
  constructor(message: string) {
    super(message);
    this.name = "UnknownBetError";
  }
}

/* ------------------------------------------------------------------ */
/* Data                                                                */
/* ------------------------------------------------------------------ */

/** A single live wager on the table. */
export interface Bet {
  kind: string;
  amount: number;
  /** Point/box number, when the bet needs one. */
  number: number | null;
}

export type BetOutcome = "won" | "lost" | "push" | "returned" | "travel";

/** What happened to one bet when a round resolved. */
export interface BetEvent {
  kind: string;
  number: number | null;
  /** Stake that was at risk. */
  amount: number;
  outcome: BetOutcome;
  /** Net profit to the player (negative on a loss). */
  profit: number;
}

/** Human-readable one-liner for a BetEvent (debugging strategies). */
export function formatBetEvent(e: BetEvent): string {
  const num = e.number != null ? ` ${e.number}` : "";
  const sign = e.profit >= 0 ? "+" : "";
  return `${e.kind}${num} $${e.amount} -> ${e.outcome} (${sign}${e.profit})`;
}

/** Summary of one resolved round, for logging / debugging. */
export interface RoundResult {
  description: string;
  events: BetEvent[];
}

/* ------------------------------------------------------------------ */
/* Table                                                               */
/* ------------------------------------------------------------------ */

export interface TableOptions {
  bankroll?: number;
  /** Seeded dice source. Omit for non-deterministic (Math.random-seeded) play. */
  seed?: number | null;
}

export abstract class Table {
  bankroll: number;
  startingBankroll: number;
  bets: Bet[] = [];
  /** Every dollar ever put at risk — the denominator for realized house edge. */
  totalWagered = 0;
  seed: number | null;

  protected rng: SeededRng;
  /** Resolved-bet event queue (drained by the engine / strategies). */
  protected pending: BetEvent[] = [];

  constructor(opts: TableOptions = {}) {
    const bankroll = opts.bankroll ?? 1000.0;
    this.bankroll = bankroll;
    this.startingBankroll = bankroll;
    this.seed = opts.seed ?? null;
    // Without a seed we still need *a* PRNG: seed it from Math.random.
    this.rng =
      this.seed != null
        ? new SeededRng(this.seed)
        : new SeededRng((Math.random() * 0xffffffff) >>> 0);
  }

  /** Draw one die (1-6) from the table's RNG. */
  protected die(): number {
    return this.rng.die();
  }

  findBet(kind: string, number: number | null = null): Bet | undefined {
    return this.bets.find((b) => b.kind === kind && b.number === number);
  }

  hasBet(kind: string, number: number | null = null): boolean {
    return this.findBet(kind, number) !== undefined;
  }

  /** Return and clear the resolved-bet events since the last call. */
  drainEvents(): BetEvent[] {
    const events = this.pending;
    this.pending = [];
    return events;
  }

  /** Append a resolved-bet event without moving money (e.g. come-bet travel). */
  protected recordEvent(event: BetEvent): BetEvent {
    this.pending.push(event);
    return event;
  }

  /** Deduct a stake from the bankroll and add it to total wagered. */
  protected charge(amount: number): void {
    if (amount > this.bankroll + 1e-9) {
      throw new InsufficientBankroll(
        `bet of $${amount} exceeds bankroll of $${this.bankroll}`
      );
    }
    this.bankroll -= amount;
    this.totalWagered += amount;
  }

  /**
   * Remove *bet* and move money. `payMult` is profit per unit staked.
   * Mirrors `Table._settle` in the Python engine exactly.
   */
  protected settle(bet: Bet, outcome: BetOutcome, payMult = 0): BetEvent {
    const idx = this.bets.indexOf(bet);
    if (idx >= 0) this.bets.splice(idx, 1);
    let profit: number;
    if (outcome === "won") {
      profit = bet.amount * payMult;
      this.bankroll += bet.amount + profit;
    } else if (outcome === "push" || outcome === "returned") {
      profit = 0;
      this.bankroll += bet.amount;
    } else {
      // lost
      profit = -bet.amount;
    }
    return this.recordEvent({
      kind: bet.kind,
      number: bet.number,
      amount: bet.amount,
      outcome,
      profit,
    });
  }

  /** Resolve one round of the game and settle every bet. */
  abstract roll(d1?: number, d2?: number): RoundResult;
}
