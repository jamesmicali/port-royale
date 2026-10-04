/**
 * Bundled craps strategies, ported concept-for-concept from
 * `strategies/craps.py`. Each is a complete, working strategy written
 * against the same `decide(table)` table API.
 */

import { LAY_PAY } from "./craps";
import type { CrapsTable } from "./craps";
import { Strategy, type ParamSpec } from "./strategy";

/** Pass line on every come-out, backed with max odds once a point is set. */
export class PassLineWithOdds extends Strategy {
  readonly name = "passline_odds";
  description = "Pass line every come-out + max odds behind it.";

  static PARAMS: Record<string, ParamSpec> = {
    base_unit: {
      type: "float",
      default: 10.0,
      label: "Base unit ($)",
      help: "Pass line bet on each come-out.",
    },
    odds_multiple: {
      type: "int",
      default: 5,
      label: "Odds multiple",
      help: "How many x the flat bet to lay in odds (capped by bankroll).",
    },
  };

  declare base_unit: number;
  declare odds_multiple: number;

  decide(table: CrapsTable): void {
    if (table.phase === "comeout") {
      if (!table.hasBet("pass") && table.bankroll >= this.base_unit) {
        table.placeBet("pass", this.base_unit);
      }
    } else {
      // point is on: load the odds behind our pass line bet
      if (table.hasBet("pass") && !table.hasOdds("pass")) {
        const want = this.base_unit * this.odds_multiple;
        const amount = Math.min(want, table.bankroll);
        if (amount >= table.minBet) {
          table.addOdds("pass", amount);
        }
      }
    }
  }
}

/** Don't pass on every come-out, then lay the maximum odds. */
export class DontPassWithOdds extends Strategy {
  readonly name = "dontpass_odds";
  description = "Don't pass every come-out + max lay odds.";

  static PARAMS: Record<string, ParamSpec> = {
    base_unit: {
      type: "float",
      default: 10.0,
      label: "Base unit ($)",
      help: "Don't pass bet on each come-out.",
    },
    odds_multiple: {
      type: "int",
      default: 5,
      label: "Odds multiple",
      help: "Win-multiple of the flat bet to lay in odds.",
    },
  };

  declare base_unit: number;
  declare odds_multiple: number;

  decide(table: CrapsTable): void {
    if (table.phase === "comeout") {
      if (!table.hasBet("dontpass") && table.bankroll >= this.base_unit) {
        table.placeBet("dontpass", this.base_unit);
      }
    } else {
      if (table.hasBet("dontpass") && !table.hasOdds("dontpass")) {
        // Lay enough to *win* `odds_multiple` x the flat bet.
        const flat = table.findBet("dontpass")!.amount;
        const cap = (this.odds_multiple * flat) / LAY_PAY[table.point as number];
        const amount = Math.min(cap, table.bankroll);
        if (amount >= table.minBet) {
          table.addOdds("dontpass", amount);
        }
      }
    }
  }
}

/**
 * The classic "can't lose" field system: pass line on the come-out, then
 * field + place 5/6/8 once the point is set, so every roll except 7 pays
 * something. Skips the point number itself — the pass line covers it.
 */
export class IronCross extends Strategy {
  readonly name = "ironcross";
  description = "Pass line + field + place 5/6/8 after the come-out.";

  static PARAMS: Record<string, ParamSpec> = {
    base_unit: {
      type: "float",
      default: 10.0,
      label: "Base unit ($)",
      help: "Pass line and field bet size.",
    },
    place_unit: {
      type: "float",
      default: 12.0,
      label: "Place bet unit ($)",
      help: "Size of each place 5/6/8 bet.",
    },
  };

  declare base_unit: number;
  declare place_unit: number;

  decide(table: CrapsTable): void {
    if (table.phase === "comeout") {
      if (!table.hasBet("pass") && table.bankroll >= this.base_unit) {
        table.placeBet("pass", this.base_unit);
      }
      return;
    }
    // Point is on: cover everything but the 7.
    if (!table.hasBet("field") && table.bankroll >= this.base_unit) {
      table.placeBet("field", this.base_unit);
    }
    for (const n of [5, 6, 8]) {
      if (n === table.point) continue; // pass line already covers the point
      if (!table.hasBet("place", n) && table.bankroll >= this.place_unit) {
        table.placeBet("place", this.place_unit, n);
      }
    }
  }
}

/* ------------------------------------------------------------------ */
/* Registry                                                            */
/* ------------------------------------------------------------------ */

type StrategyCtor = new (params?: Record<string, unknown>) => Strategy;

export const STRATEGIES: Record<string, StrategyCtor> = {
  passline_odds: PassLineWithOdds,
  dontpass_odds: DontPassWithOdds,
  ironcross: IronCross,
};

export function makeStrategy(
  name: string,
  params: Record<string, unknown> = {}
): Strategy {
  const Ctor = STRATEGIES[name];
  if (!Ctor) {
    throw new Error(
      `unknown strategy ${JSON.stringify(name)}; available: ${Object.keys(
        STRATEGIES
      ).sort()}`
    );
  }
  return new Ctor(params);
}

export function listStrategies(): string[] {
  return Object.keys(STRATEGIES).sort();
}
