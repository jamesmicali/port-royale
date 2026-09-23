# Port Royale — Mobile Roadmap

**Goal:** ship Port Royale as native iOS and Android apps (App Store + Google Play).

## Why this document exists

The v0.1 stack (Python engine + Streamlit web UI + CLI) cannot ship as a native
mobile app:

- **Streamlit** is a server-side web framework. It is not embeddable in a native
  app shell in any shippable way.
- **Python** has no production-viable path to the App Store for a polished
  consumer app (BeeWare/Kivy exist, but are niche and fragile).
- The desktop workflow — "write strategies in Python files, run in a terminal" —
  assumes a keyboard and a dev environment. Wrong UX for phones.

So the mobile app will be a **rewrite of the interface layers**, not a port of
the code. This document records the target architecture and the guardrails that
keep the current codebase from drifting away from it.

## Target architecture

- **Cross-platform mobile: React Native + TypeScript**, built with Expo EAS for
  both stores.
  - Why React Native over Flutter: the product's soul is *"users write strategy
    code."* In React Native, strategy code is JavaScript and runs in the app's
    own JS runtime (Hermes) — the direct mobile analog of "write Python" on
    desktop. Flutter would need a bolted-on interpreter.
  - Why React Native over native Swift/Kotlin: one codebase, and a future web
    UI can share the core via React Native Web.
- **Shared core in TypeScript**: game engines (craps first), the strategy
  framework, and the Monte Carlo sim — ported from the Python implementation,
  which remains the **reference spec**. Engine semantics must stay in lockstep;
  shared test vectors (exact payouts, edge cases) verify the port.
- **Strategy authoring on mobile**: an in-app code editor where users write
  JavaScript against the same `decide(table)` table API. A visual block-based
  builder for non-coders can sit on top of the same API later.
- **The desktop Python app remains** as the power-user lab and reference
  implementation. It is not throwaway.
- **Watch mode is the shared playback format.** The engine's per-roll event
  stream (`watch_session`, schema in `docs/watch-mode.md`) is the
  cross-platform contract: the mobile table renders these JSON events, and
  the TypeScript port must reproduce the schema exactly.

## Interactive table & animations

The "playable craps table" vision — not just simulations, but a visual game
with rolling dice and moving chips — fits this stack well:

- **React Native Reanimated** for all motion: dice tumbles, chips sliding to
  betting spots, win highlights, losing bets getting swept. Animations run on
  the UI thread at 60/120fps, independent of the JS thread — so a Monte Carlo
  sim can crunch in the background without dropping frames.
- **React Native Skia** for custom canvas rendering: table felt, betting
  layout, chip stacks, dice faces. Full draw control beats composing a craps
  table from stock components.
- **Gesture Handler** for touch: drag chips onto the layout, tap to
  place/remove bets.
- Dice animation: choreographed tumbling (springs/keyframes) tends to look
  better than real rigid-body physics; Lottie is an option for pre-baked
  sequences.

Architecture note: the interactive table and the simulator share the same
rules core. The table UI is just a visual player making `place_bet` / `roll`
calls against the engine — so every animation stays honest to the real odds,
and strategies can be watched playing themselves out bet by bet.

## What ports vs. what gets replaced

| Layer | Mobile fate |
|---|---|
| `games/` engines (rules, payouts) | Port concept-for-concept to TypeScript |
| `strategies/` framework + table API | Port; the table API is the cross-platform contract |
| `sim.py` statistics | Port |
| Bundled strategies (`passline_odds`, …) | Port (they're just `decide()` logic) |
| Streamlit `app.py` | Replaced by the React Native UI |
| `cli.py` | Replaced (phones have no terminal) |

## Guardrails for future work (until the mobile port starts)

1. **Keep the engine UI-free.** Nothing in `games/`, `strategies/`, or `sim.py`
   may import from UI/CLI layers. (True today — keep it that way.)
2. **No Python-only strategy-framework features.** Nothing that can't map to the
   JS table API: no numpy-vectorized strategy hooks, no metaclass magic, no
   `eval` tricks. If a feature can't be expressed as `decide(table)` + the
   documented table API, it doesn't go in.
3. **New engine rules go in `games/` with tests.** The TypeScript port treats
   this repo as the spec; untested behavior can't be ported faithfully.
4. **Limit further Streamlit investment.** It's the desktop lab, not the
   future. New UI work should be justifiable as prototype-only.
5. **The table API is the contract.** Changes to it are cross-platform
   decisions — update this doc's API table when it changes.

## Alternatives considered

- **Hosted Python backend + thin mobile client.** Preserves Python strategies
  server-side, but adds hosting cost, latency, and offline problems — and
  editing code on a phone is still bad UX. Rejected for v1; could return for
  very heavy sims.
- **Flutter.** Excellent UI toolkit, weak story for user-written strategy code.
- **BeeWare / Kivy.** Ships Python on mobile, but immature for a polished
  consumer app.

## Store & business notes

- **No real-money gambling, ever, without legal review.** As an educational
  simulator with no real-money play, no gambling license is needed on either
  store. Keep it that way.
- **Monetization later:** subscriptions or one-time unlock via store billing
  (e.g. Expo IAP / RevenueCat) — never web checkout inside the app.
- **Performance budget:** Hermes (the RN JS runtime) is slower than desktop
  Python+numpy for tight loops. The TS sim should target ~100 sessions × a few
  thousand rolls interactively; larger runs can be chunked across frames or
  moved to a background task. Validate with benchmarks during the port.
