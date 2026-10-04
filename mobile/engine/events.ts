/**
 * Watch-mode event schema — the cross-platform contract.
 *
 * These TypeScript types reproduce `docs/watch-mode.md` exactly: same
 * event type names, same field names (snake_case, matching the Python
 * dicts key-for-key). The future mobile table renders these JSON events;
 * any producer must emit these six types with these fields.
 *
 * `session_end` may carry an extra `error` string when `reason` is
 * "error". Viewers should treat unknown future fields as ignorable.
 */

export interface SessionStartEvent {
  type: "session_start";
  game: string;
  strategy: string;
  strategy_params: Record<string, unknown>;
  seed: number | null;
  bankroll: number;
  rolls: number;
  stop_loss: number | null;
  stop_win: number | null;
  min_bet: number;
  max_bet: number;
  odds_multiple: number;
}

export interface BetPlacedEvent {
  type: "bet_placed";
  roll: number;
  kind: string;
  amount: number;
  number: number | null;
}

export type ResolvedOutcome = "won" | "lost" | "push" | "returned" | "travel";

export interface BetResolvedEvent {
  type: "bet_resolved";
  roll: number;
  kind: string;
  number: number | null;
  amount: number;
  outcome: ResolvedOutcome;
  /** Net profit to the player (negative on a loss, 0 on push/return/travel). */
  profit: number;
}

export interface RollEvent {
  type: "roll";
  /** 1-based per-roll sequence number. */
  roll: number;
  d1: number;
  d2: number;
  total: number;
  /** Phase *after* the roll resolved. */
  phase: "comeout" | "point";
  /** Point *after* the roll resolved; null on come-out. */
  point: number | null;
}

export interface BankrollEvent {
  type: "bankroll";
  roll: number;
  bankroll: number;
}

export type SessionEndReason =
  | "rolls_exhausted"
  | "ruin"
  | "stop_loss"
  | "stop_win"
  | "error";

export interface SessionEndEvent {
  type: "session_end";
  reason: SessionEndReason;
  rolls_played: number;
  final_bankroll: number;
  net_profit: number;
  total_wagered: number;
  max_drawdown: number;
  /** Present only when reason === "error". */
  error?: string;
}

export type WatchEvent =
  | SessionStartEvent
  | BetPlacedEvent
  | BetResolvedEvent
  | RollEvent
  | BankrollEvent
  | SessionEndEvent;

/** The six event types of the stable contract. */
export const WATCH_EVENT_TYPES = [
  "session_start",
  "bet_placed",
  "bet_resolved",
  "roll",
  "bankroll",
  "session_end",
] as const;
