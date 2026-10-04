/**
 * Seeded deterministic PRNG for the Port Royale engine.
 *
 * The Python reference implementation draws dice from `random.Random(seed)`
 * (Mersenne Twister). JavaScript has no built-in equivalent, so this port
 * uses mulberry32 — a small, fast, well-tested 32-bit PRNG.
 *
 * **Seeds are NOT cross-compatible with Python.** `seed=42` in TypeScript
 * produces a *different* dice stream than `seed=42` in Python. What the
 * contract guarantees is per-platform determinism: the same seed on the
 * same platform always replays the identical session, event for event.
 * Cross-platform checks compare *statistics and the event schema*, never
 * raw dice sequences.
 */

/** Mulberry32: returns a function yielding uniform floats in [0, 1). */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function (): number {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Integer-drawing RNG wrapper. One instance per table (or per dice stream),
 * mirroring how the Python engine gives each table its own `random.Random`.
 */
export class SeededRng {
  private readonly rand: () => number;

  constructor(seed: number) {
    this.rand = mulberry32(seed);
  }

  /** Uniform float in [0, 1). */
  float(): number {
    return this.rand();
  }

  /**
   * Uniform integer in [low, high], inclusive — like Python's
   * `random.randint(low, high)`.
   */
  int(low: number, high: number): number {
    return low + Math.floor(this.rand() * (high - low + 1));
  }

  /** One six-sided die. */
  die(): number {
    return this.int(1, 6);
  }
}
