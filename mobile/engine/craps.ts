/**
 * A correct, fully-featured craps table engine.
 *
 * Concept-for-concept port of `games/craps.py`. The table owns the game
 * state — phase (come-out / point), the point, bankroll and every live bet
 * — and resolves each roll with true casino payouts. Strategies observe
 * the table and place/remove bets; the engine enforces table
 * minimums/maximums, odds multiples and bankroll.
 *
 * House rules modelled (same as Python):
 * - Don't pass / don't come are barred on 12 (push).
 * - Place / buy / lay / hardway bets are *off* on come-out rolls.
 * - Pass / don't pass may only be placed on a come-out roll;
 *   come / don't come only while a point is established.
 * - Odds pay true odds: 2:1 on 4 & 10, 3:2 on 5 & 9, 6:5 on 6 & 8
 *   (don't side is the mirror image: 1:2, 2:3, 5:6).
 * - Place bets pay 9:5 (4/10), 7:5 (5/9), 7:6 (6/8).
 * - Buy bets pay true odds less 5% commission on the win; lay bets mirror it.
 * - Field pays 2:1 on 2 and 12, 1:1 on 3/4/9/10/11.
 * - Hardways pay 7:1 (4/10) and 9:1 (6/8); lose on 7 or the easy way.
 *
 * UI-free: no React / React Native imports.
 */

import {
  Bet,
  BetEvent,
  RoundResult,
  Table,
  TableLimitError,
  UnknownBetError,
} from "./table";

export const POINT_NUMBERS = [4, 5, 6, 8, 9, 10] as const;
export const HARD_NUMBERS = [4, 6, 8, 10] as const;

/** Profit per unit staked. */
export const ODDS_PAY: Record<number, number> = {
  4: 2.0,
  10: 2.0,
  5: 1.5,
  9: 1.5,
  6: 6 / 5,
  8: 6 / 5,
};
export const LAY_PAY: Record<number, number> = {
  4: 1 / 2,
  10: 1 / 2,
  5: 2 / 3,
  9: 2 / 3,
  6: 5 / 6,
  8: 5 / 6,
};
export const PLACE_PAY: Record<number, number> = {
  4: 9 / 5,
  10: 9 / 5,
  5: 7 / 5,
  9: 7 / 5,
  6: 7 / 6,
  8: 7 / 6,
};
/** 5% commission on the win. */
export const BUY_PAY: Record<number, number> = Object.fromEntries(
  Object.entries(ODDS_PAY).map(([n, p]) => [n, p * 0.95])
);
export const LAY_BET_PAY: Record<number, number> = Object.fromEntries(
  Object.entries(LAY_PAY).map(([n, p]) => [n, p * 0.95])
);
export const HARD_PAY: Record<number, number> = { 4: 7.0, 10: 7.0, 6: 9.0, 8: 9.0 };
export const FIELD_PAY: Record<number, number> = {
  2: 2.0,
  12: 2.0,
  3: 1.0,
  4: 1.0,
  9: 1.0,
  10: 1.0,
  11: 1.0,
};
export const PROP_PAY: Record<string, number> = {
  any_seven: 4.0,
  any_craps: 7.0,
  two_twelve: 30.0,
  three_eleven: 15.0,
};
export const PROP_WINNERS: Record<string, number[]> = {
  any_seven: [7],
  any_craps: [2, 3, 12],
  two_twelve: [2, 12],
  three_eleven: [3, 11],
};

const ODDS_KINDS = ["pass_odds", "dontpass_odds", "come_odds", "dontcome_odds"];
const FLAT_FOR_ODDS: Record<string, string> = {
  pass: "pass_odds",
  dontpass: "dontpass_odds",
  come: "come_odds",
  dontcome: "dontcome_odds",
};

export type CrapsPhase = "comeout" | "point";

export interface CrapsRollResult extends RoundResult {
  d1: number;
  d2: number;
  total: number;
  phase: CrapsPhase;
  point: number | null;
}

export interface CrapsTableOptions {
  bankroll?: number;
  minBet?: number;
  maxBet?: number;
  oddsMultiple?: number;
  seed?: number | null;
}

export class CrapsTable extends Table {
  minBet: number;
  maxBet: number;
  oddsMultiple: number;
  phase: CrapsPhase = "comeout";
  point: number | null = null;
  rollCount = 0;
  shooterRolls = 0;
  lastRoll: [number, number] | null = null;

  constructor(opts: CrapsTableOptions = {}) {
    super({ bankroll: opts.bankroll, seed: opts.seed });
    this.minBet = opts.minBet ?? 5.0;
    this.maxBet = opts.maxBet ?? 5000.0;
    this.oddsMultiple = Math.trunc(opts.oddsMultiple ?? 5);
  }

  /* ---------------------------------------------------------------- */
  /* Placing / removing bets                                           */
  /* ---------------------------------------------------------------- */

  /**
   * Place a new bet, deducting it from the bankroll.
   * Odds bets are never placed directly — use `addOdds`.
   */
  placeBet(kind: string, amount: number, number: number | null = null): Bet {
    amount = Number(amount);
    this.validateBet(kind, amount, number);
    this.charge(amount);
    const bet: Bet = { kind, amount, number };
    this.bets.push(bet);
    return bet;
  }

  private validateBet(
    kind: string,
    amount: number,
    number: number | null
  ): void {
    if (amount < this.minBet - 1e-9) {
      throw new TableLimitError(
        `$${amount} is below the $${this.minBet} minimum`
      );
    }
    if (amount > this.maxBet + 1e-9) {
      throw new TableLimitError(
        `$${amount} is above the $${this.maxBet} maximum`
      );
    }

    if (kind === "pass" || kind === "dontpass") {
      if (number !== null && number !== undefined) {
        throw new TableLimitError(`${kind} takes no number`);
      }
      if (this.phase !== "comeout") {
        throw new TableLimitError(`${kind} can only be bet on a come-out roll`);
      }
    } else if (kind === "come" || kind === "dontcome") {
      if (number !== null && number !== undefined) {
        throw new TableLimitError(`${kind} starts in transit (no number yet)`);
      }
      if (this.phase !== "point") {
        throw new TableLimitError(`${kind} can only be bet while a point is on`);
      }
    } else if (ODDS_KINDS.includes(kind)) {
      throw new TableLimitError(`use addOdds() to place ${kind}`);
    } else if (kind === "place" || kind === "buy" || kind === "lay") {
      if (!(POINT_NUMBERS as readonly number[]).includes(number as number)) {
        throw new TableLimitError(
          `${kind} needs a box number ${POINT_NUMBERS}`
        );
      }
      if (this.phase !== "point") {
        throw new TableLimitError(`${kind} bets are off on the come-out`);
      }
    } else if (kind === "hard") {
      if (!(HARD_NUMBERS as readonly number[]).includes(number as number)) {
        throw new TableLimitError(
          `hardway needs a number in ${HARD_NUMBERS}`
        );
      }
    } else if (kind === "field") {
      if (number !== null && number !== undefined) {
        throw new TableLimitError("field takes no number");
      }
    } else if (kind in PROP_PAY) {
      if (number !== null && number !== undefined) {
        throw new TableLimitError(`${kind} takes no number`);
      }
    } else {
      throw new UnknownBetError(`unknown bet kind: ${JSON.stringify(kind)}`);
    }
  }

  /**
   * Add odds behind a flat pass/don't-pass/come/don't-come bet.
   *
   * `kind` is the *flat* bet kind; for come/don't-come give the box
   * `number` of the established bet. The odds cap is `oddsMultiple` x the
   * flat bet (measured by *profit* you can win, so don't-side caps are
   * converted with the lay ratio).
   */
  addOdds(
    kind: string,
    amount: number,
    number: number | null = null
  ): Bet {
    if (!(kind in FLAT_FOR_ODDS)) {
      throw new UnknownBetError(`cannot take odds on ${JSON.stringify(kind)}`);
    }
    amount = Number(amount);
    const flat = this.findBet(kind, number);
    if (!flat) {
      throw new TableLimitError(`no ${kind} bet to put odds behind`);
    }
    if ((kind === "pass" || kind === "dontpass") && this.phase !== "point") {
      throw new TableLimitError("odds can only be added while a point is on");
    }

    const pointNo =
      kind === "pass" || kind === "dontpass" ? this.point : flat.number;
    if (pointNo == null) {
      throw new TableLimitError("that bet has no number yet (still in transit)");
    }

    let cap: number;
    if (kind === "pass" || kind === "come") {
      cap = this.oddsMultiple * flat.amount;
    } else {
      // don't side: the multiple applies to what you can WIN
      cap = (this.oddsMultiple * flat.amount) / LAY_PAY[pointNo];
    }
    if (amount > cap + 1e-9) {
      throw new TableLimitError(
        `$${amount} odds exceeds ${this.oddsMultiple}x (max $${cap} on this bet)`
      );
    }
    if (amount < this.minBet - 1e-9) {
      throw new TableLimitError(
        `$${amount} is below the $${this.minBet} minimum`
      );
    }

    this.charge(amount);
    const bet: Bet = { kind: FLAT_FOR_ODDS[kind], amount, number: pointNo };
    this.bets.push(bet);
    return bet;
  }

  /** Remove a bet and refund its stake (odds & come bets excepted). */
  takeDown(kind: string, number: number | null = null): Bet {
    const bet = this.findBet(kind, number);
    if (!bet) {
      throw new TableLimitError(`no ${kind} bet to take down`);
    }
    if (ODDS_KINDS.includes(kind)) {
      throw new TableLimitError(
        "odds can't be taken down while the flat bet lives"
      );
    }
    this.settle(bet, "returned");
    return bet;
  }

  /**
   * Is there an odds bet behind flat bet `kind`?
   *
   * `kind` is the *flat* bet kind ("pass", "dontpass", "come", "dontcome");
   * `number` optionally pins it to one box number (needed for
   * come/don't-come). Prefer this over `hasBet("pass_odds")` — odds bets
   * store the point number, so a plain `hasBet` lookup with
   * `number=null` never matches them.
   */
  hasOdds(kind: string, number: number | null = null): boolean {
    if (!(kind in FLAT_FOR_ODDS)) {
      throw new UnknownBetError(`no odds exist for ${JSON.stringify(kind)}`);
    }
    const oddsKind = FLAT_FOR_ODDS[kind];
    return this.bets.some(
      (b) => b.kind === oddsKind && (number == null || b.number === number)
    );
  }

  /* ---------------------------------------------------------------- */
  /* Rolling                                                           */
  /* ---------------------------------------------------------------- */

  /** Roll the dice (random unless `d1`/`d2` given) and settle bets. */
  roll(d1?: number, d2?: number): CrapsRollResult {
    if (d1 === undefined || d2 === undefined) {
      d1 = this.die();
      d2 = this.die();
    }
    const total = d1 + d2;
    this.lastRoll = [d1, d2];
    this.rollCount += 1;
    this.shooterRolls += 1;

    const eventsBefore = this.pending.length;
    for (const bet of [...this.bets]) {
      // copy: settling mutates the list
      this.resolveBet(bet, total, d1 === d2);
    }

    // Phase transitions happen after every bet has seen the roll.
    if (this.phase === "comeout" && (POINT_NUMBERS as readonly number[]).includes(total)) {
      this.phase = "point";
      this.point = total;
    } else if (
      this.phase === "point" &&
      (total === 7 || total === this.point)
    ) {
      const sevenOut = total === 7;
      this.phase = "comeout";
      this.point = null;
      if (sevenOut) {
        this.shooterRolls = 0; // new shooter
      }
    }

    return {
      description:
        `${d1}-${d2} = ${total} (${this.phase}` +
        (this.point ? `, point ${this.point}` : "") +
        `)`,
      events: this.pending.slice(eventsBefore),
      d1,
      d2,
      total,
      phase: this.phase,
      point: this.point,
    };
  }

  /* ---------------------------------------------------------------- */
  /* Resolution                                                        */
  /* ---------------------------------------------------------------- */

  private resolveBet(bet: Bet, total: number, hard: boolean): void {
    const kind = bet.kind;
    const n = bet.number;

    // -- one-roll bets: always live -----------------------------------
    if (kind === "field") {
      const pay = FIELD_PAY[total];
      this.settle(bet, pay !== undefined ? "won" : "lost", pay ?? 0);
      return;
    }
    if (kind in PROP_PAY) {
      const won = PROP_WINNERS[kind].includes(total);
      this.settle(bet, won ? "won" : "lost", won ? PROP_PAY[kind] : 0);
      return;
    }

    // -- hardways: off on the come-out --------------------------------
    if (kind === "hard") {
      if (this.phase === "comeout") return;
      if (total === 7 || total === n) {
        if (total === n && hard) {
          this.settle(bet, "won", HARD_PAY[n as number]);
        } else {
          this.settle(bet, "lost");
        }
      }
      return;
    }

    // -- line & come bets ---------------------------------------------
    if (kind === "pass") {
      if (this.phase === "comeout") {
        if (total === 7 || total === 11) this.settle(bet, "won", 1.0);
        else if (total === 2 || total === 3 || total === 12)
          this.settle(bet, "lost");
      } else {
        if (total === 7) this.settle(bet, "lost");
        else if (total === this.point) this.settle(bet, "won", 1.0);
      }
      return;
    }

    if (kind === "dontpass") {
      if (this.phase === "comeout") {
        if (total === 2 || total === 3) this.settle(bet, "won", 1.0);
        else if (total === 12) this.settle(bet, "push");
        else if (total === 7 || total === 11) this.settle(bet, "lost");
      } else {
        if (total === 7) this.settle(bet, "won", 1.0);
        else if (total === this.point) this.settle(bet, "lost");
      }
      return;
    }

    if (kind === "pass_odds") {
      if (total === 7) this.settle(bet, "lost");
      else if (total === n) this.settle(bet, "won", ODDS_PAY[n as number]);
      return;
    }

    if (kind === "dontpass_odds") {
      if (total === 7) this.settle(bet, "won", LAY_PAY[n as number]);
      else if (total === n) this.settle(bet, "lost");
      return;
    }

    if (kind === "come") {
      if (n === null || n === undefined) {
        // in transit: works like a fresh pass-line roll
        if (total === 7 || total === 11) this.settle(bet, "won", 1.0);
        else if (total === 2 || total === 3 || total === 12)
          this.settle(bet, "lost");
        else {
          bet.number = total;
          this.recordEvent({
            kind,
            number: total,
            amount: bet.amount,
            outcome: "travel",
            profit: 0,
          });
        }
      } else {
        if (total === 7) this.settle(bet, "lost");
        else if (total === n) this.settle(bet, "won", 1.0);
      }
      return;
    }

    if (kind === "dontcome") {
      if (n === null || n === undefined) {
        if (total === 2 || total === 3) this.settle(bet, "won", 1.0);
        else if (total === 12) this.settle(bet, "push");
        else if (total === 7 || total === 11) this.settle(bet, "lost");
        else {
          bet.number = total;
          this.recordEvent({
            kind,
            number: total,
            amount: bet.amount,
            outcome: "travel",
            profit: 0,
          });
        }
      } else {
        if (total === 7) this.settle(bet, "won", 1.0);
        else if (total === n) this.settle(bet, "lost");
      }
      return;
    }

    if (kind === "come_odds") {
      if (total === 7) this.settle(bet, "lost");
      else if (total === n) this.settle(bet, "won", ODDS_PAY[n as number]);
      return;
    }

    if (kind === "dontcome_odds") {
      if (total === 7) this.settle(bet, "won", LAY_PAY[n as number]);
      else if (total === n) this.settle(bet, "lost");
      return;
    }

    // -- place / buy / lay: off on the come-out ------------------------
    if (kind === "place" || kind === "buy" || kind === "lay") {
      if (this.phase === "comeout") return;
      if (kind === "place") {
        if (total === n) this.settle(bet, "won", PLACE_PAY[n as number]);
        else if (total === 7) this.settle(bet, "lost");
      } else if (kind === "buy") {
        if (total === n) this.settle(bet, "won", BUY_PAY[n as number]);
        else if (total === 7) this.settle(bet, "lost");
      } else {
        // lay
        if (total === 7) this.settle(bet, "won", LAY_BET_PAY[n as number]);
        else if (total === n) this.settle(bet, "lost");
      }
      return;
    }

    throw new UnknownBetError(
      `cannot resolve unknown bet kind: ${JSON.stringify(kind)}`
    );
  }
}
