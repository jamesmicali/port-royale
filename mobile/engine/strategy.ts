/**
 * The strategy framework.
 *
 * A strategy is a small object that watches the table and bets. Before
 * every round the engine calls `strategy.decide(table)`; the strategy
 * reads the table state (phase, point, bankroll, live bets, recent events)
 * and calls `table.placeBet(...)` / `table.addOdds(...)` /
 * `table.takeDown(...)` directly.
 *
 * Strategies may keep memory between rounds (`onSessionStart` resets it)
 * and learn what just happened via `table.drainEvents()`.
 *
 * Each strategy declares its knobs in `PARAMS` so future UI can configure
 * it without touching code. Port of `strategies/base.py` — UI-free.
 */

import type { CrapsTable } from "./craps";

export type ParamType = "int" | "float" | "bool" | "str";

export interface ParamSpec {
  type: ParamType;
  default: number | boolean | string;
  label?: string;
  help?: string;
}

function castParam(spec: ParamSpec, raw: unknown): number | boolean | string {
  switch (spec.type) {
    case "int":
      return Math.trunc(Number(raw));
    case "float":
      return Number(raw);
    case "bool":
      return Boolean(raw);
    case "str":
      return String(raw);
  }
}

export abstract class Strategy {
  /** Registry key, e.g. "passline_odds". */
  readonly name: string = "base";
  description = "";

  static PARAMS: Record<string, ParamSpec> = {};

  constructor(params: Record<string, unknown> = {}) {
    const PARAMS: Record<string, ParamSpec> = (
      this.constructor as typeof Strategy
    ).PARAMS;
    for (const [key, spec] of Object.entries(PARAMS)) {
      const raw = key in params ? params[key] : spec.default;
      (this as Record<string, unknown>)[key] = castParam(spec, raw);
    }
    const unknown = Object.keys(params).filter((k) => !(k in PARAMS));
    if (unknown.length > 0) {
      throw new Error(
        `unknown params for ${this.name}: ${unknown.sort().join(", ")}`
      );
    }
  }

  /** Reset any per-session memory. Called once before the first roll. */
  onSessionStart(_table: CrapsTable): void {
    // default: stateless
  }

  /** Observe the table and place / adjust bets before the next round. */
  abstract decide(table: CrapsTable): void;
}
