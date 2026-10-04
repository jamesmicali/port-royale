/**
 * Bet-resolution correctness tests for the TypeScript craps engine.
 * Mirrors the rule coverage of tests/test_craps.py: exact payouts,
 * bar-12, hardways, place/buy/field math, come-bet travel, table limits.
 */
import {
  BUY_PAY,
  CrapsTable,
  HARD_PAY,
  LAY_PAY,
  ODDS_PAY,
  PLACE_PAY,
} from "../craps";
import {
  InsufficientBankroll,
  TableError,
  TableLimitError,
  UnknownBetError,
} from "../table";

function table(bankroll = 1000): CrapsTable {
  return new CrapsTable({ bankroll });
}

test("pass line wins 1:1 on a come-out natural", () => {
  const t = table();
  t.placeBet("pass", 10);
  const r = t.roll(3, 4);
  expect(r.total).toBe(7);
  expect(r.phase).toBe("comeout");
  expect(t.bankroll).toBeCloseTo(1010, 9);
  expect(t.drainEvents()).toEqual([
    expect.objectContaining({ kind: "pass", outcome: "won", profit: 10 }),
  ]);
});

test("pass line loses on come-out craps", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(1, 1);
  expect(t.bankroll).toBeCloseTo(990, 9);
  expect(t.drainEvents()).toEqual([
    expect.objectContaining({ kind: "pass", outcome: "lost", profit: -10 }),
  ]);
});

test("point established, then made, wins the pass line", () => {
  const t = table();
  t.placeBet("pass", 10);
  let r = t.roll(3, 3); // point 6
  expect(r.phase).toBe("point");
  expect(t.point).toBe(6);
  r = t.roll(2, 4); // point made
  expect(r.phase).toBe("comeout");
  expect(t.bankroll).toBeCloseTo(1010, 9);
});

test("seven-out loses the pass line and resets the shooter", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(3, 3); // point 6
  t.roll(4, 3); // seven-out
  expect(t.phase).toBe("comeout");
  expect(t.point).toBeNull();
  expect(t.shooterRolls).toBe(0);
  expect(t.bankroll).toBeCloseTo(990, 9);
});

test("don't pass is barred (push) on 12", () => {
  const t = table();
  t.placeBet("dontpass", 10);
  t.roll(6, 6);
  expect(t.bankroll).toBeCloseTo(1000, 9); // stake returned
  expect(t.drainEvents()).toEqual([
    expect.objectContaining({ kind: "dontpass", outcome: "push", profit: 0 }),
  ]);
});

test("don't pass wins on seven-out", () => {
  const t = table();
  t.placeBet("dontpass", 10);
  t.roll(2, 4); // point 6
  t.roll(4, 3); // seven-out
  expect(t.bankroll).toBeCloseTo(1010, 9);
});

test("pass odds pay true odds (6:5 on 6/8)", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(3, 3); // point 6
  t.addOdds("pass", 50); // 5x
  expect(t.hasOdds("pass")).toBe(true);
  t.roll(4, 2); // point made: flat wins $10, odds win $60
  expect(t.bankroll).toBeCloseTo(1000 - 10 - 50 + 20 + 110, 9);
  const oddsEvent = t
    .drainEvents()
    .find((e) => e.kind === "pass_odds");
  expect(oddsEvent).toMatchObject({ outcome: "won", profit: 50 * ODDS_PAY[6] });
});

test("don't pass lay odds pay the mirror (5:6 on 6/8)", () => {
  const t = table();
  t.placeBet("dontpass", 10);
  t.roll(3, 3); // point 6
  // lay enough to win $50: 50 / (5/6) = $60
  t.addOdds("dontpass", 60);
  t.roll(4, 3); // seven-out: flat wins $10, odds win $50
  expect(t.bankroll).toBeCloseTo(1000 - 10 - 60 + 20 + 110, 9);
  const oddsEvent = t
    .drainEvents()
    .find((e) => e.kind === "dontpass_odds");
  expect(oddsEvent).toMatchObject({ outcome: "won", profit: 60 * LAY_PAY[6] });
});

test("place 6 pays 7:6", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(3, 3); // point 6
  t.placeBet("place", 12, 6);
  t.roll(4, 2);
  const ev = t.drainEvents().find((e) => e.kind === "place");
  expect(ev).toMatchObject({ outcome: "won", profit: 12 * PLACE_PAY[6] });
  expect(ev!.profit).toBeCloseTo(14, 9);
});

test("field pays 2:1 on 2 and 12, 1:1 on 3/4/9/10/11", () => {
  const t = table();
  t.placeBet("field", 10);
  t.roll(1, 1);
  expect(t.bankroll).toBeCloseTo(1000 - 10 + 30, 9); // stake + $20
  t.placeBet("field", 10);
  t.roll(2, 3); // 5: field loses
  expect(t.bankroll).toBeCloseTo(1000 + 20 - 10, 9);
});

test("hardway wins 9:1 on the hard roll, loses on the easy roll or 7", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(3, 3); // point on (hardways are off on come-out)
  t.placeBet("hard", 10, 8);
  t.roll(4, 4); // hard 8
  let ev = t.drainEvents().find((e) => e.kind === "hard");
  expect(ev).toMatchObject({ outcome: "won", profit: 10 * HARD_PAY[8] });

  t.placeBet("hard", 10, 8);
  t.roll(5, 3); // easy 8
  ev = t.drainEvents().find((e) => e.kind === "hard");
  expect(ev).toMatchObject({ outcome: "lost", profit: -10 });
});

test("buy pays true odds less 5% commission", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(2, 2); // point 4
  t.placeBet("buy", 20, 4);
  t.roll(3, 1); // point made
  const ev = t.drainEvents().find((e) => e.kind === "buy");
  expect(ev).toMatchObject({ outcome: "won" });
  expect(ev!.profit).toBeCloseTo(20 * BUY_PAY[4], 9); // 2:1 less 5% = $38
});

test("come bet travels to a box number then wins", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(3, 3); // point 6
  t.placeBet("come", 10); // in transit
  t.roll(2, 3); // 5: come travels to 5
  const travel = t.drainEvents().find((e) => e.outcome === "travel");
  expect(travel).toMatchObject({ kind: "come", number: 5, profit: 0 });
  expect(t.hasBet("come", 5)).toBe(true);
  t.roll(3, 2); // 5 again: come wins $10 on the $10 stake
  expect(t.bankroll).toBeCloseTo(1000, 9); // 980 + 20 returned; pass line still live
});

test("table minimum is enforced", () => {
  const t = table();
  expect(() => t.placeBet("pass", 1)).toThrow(TableLimitError);
  expect(() => t.placeBet("pass", 1)).toThrow(TableError);
});

test("unknown bet kinds are rejected", () => {
  const t = table();
  expect(() => t.placeBet("hop_bet", 10)).toThrow(UnknownBetError);
});

test("odds cannot be placed directly", () => {
  const t = table();
  expect(() => t.placeBet("pass_odds", 10, 6)).toThrow(TableLimitError);
});

test("addOdds requires a live flat bet", () => {
  const t = table();
  expect(() => t.addOdds("pass", 10)).toThrow(TableLimitError);
});

test("odds cap is enforced at 5x the flat bet", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(3, 3); // point 6
  expect(() => t.addOdds("pass", 51)).toThrow(TableLimitError);
  expect(() => t.addOdds("pass", 50)).not.toThrow();
});

test("insufficient bankroll raises", () => {
  const t = table(20);
  expect(() => t.placeBet("pass", 25)).toThrow(InsufficientBankroll);
});

test("pass cannot be placed while a point is on", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(3, 3);
  expect(() => t.placeBet("pass", 10)).toThrow(TableLimitError);
});

test("takeDown refunds the stake", () => {
  const t = table();
  t.placeBet("pass", 10);
  t.roll(3, 3); // point 6
  t.placeBet("place", 12, 8);
  t.takeDown("place", 8);
  expect(t.bankroll).toBeCloseTo(1000 - 10, 9);
  expect(t.drainEvents().find((e) => e.kind === "place")).toMatchObject({
    outcome: "returned",
    profit: 0,
  });
});

test("seeded tables produce deterministic dice", () => {
  const a = new CrapsTable({ seed: 123 });
  const b = new CrapsTable({ seed: 123 });
  const ra = Array.from({ length: 30 }, () => a.roll().total);
  const rb = Array.from({ length: 30 }, () => b.roll().total);
  expect(ra).toEqual(rb);
});
