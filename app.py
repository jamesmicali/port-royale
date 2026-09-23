"""Port Royale — Streamlit strategy lab.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import os
import time

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from portroyale import __version__
from portroyale.games import list_games
from portroyale.sim import SimConfig, TableConfig, run_simulation, watch_session
from portroyale.strategies import STRATEGIES, list_strategies

st.set_page_config(page_title="Port Royale", page_icon="🎲", layout="wide")
st.title("🎲 Port Royale — Casino Strategy Lab")
st.caption(f"v{__version__} · define a strategy, Monte Carlo it, see the math")

# ---------------------------------------------------------------- sidebar ---
with st.sidebar:
    mode = st.radio("Mode", ["Simulate", "Watch"], horizontal=True,
                    help="Simulate: Monte Carlo stats. Watch: play one "
                         "session roll by roll.")
    st.header("Setup")
    game = st.selectbox("Game", list_games(), index=0)
    strategy_names = sorted(STRATEGIES)
    strategy_name = st.selectbox("Strategy", strategy_names, index=0)
    cls = STRATEGIES[strategy_name]
    st.caption(cls.description)

    st.subheader("Strategy parameters")
    params: dict = {}
    for key, spec in cls.PARAMS.items():
        ptype = spec.get("type", "float")
        label = spec.get("label", key)
        default = spec.get("default")
        help_text = spec.get("help", "")
        if ptype == "int":
            params[key] = st.number_input(label, value=int(default),
                                          step=1, help=help_text)
        elif ptype == "bool":
            params[key] = st.checkbox(label, value=bool(default), help=help_text)
        elif ptype == "str":
            params[key] = st.text_input(label, value=str(default), help=help_text)
        else:
            params[key] = st.number_input(label, value=float(default),
                                          step=1.0, help=help_text)

    st.subheader("Table")
    bankroll = st.number_input("Starting bankroll ($)", value=1000.0,
                               min_value=10.0, step=100.0)
    col_a, col_b = st.columns(2)
    min_bet = col_a.number_input("Min bet", value=5.0, min_value=1.0)
    max_bet = col_b.number_input("Max bet", value=5000.0, min_value=10.0)
    odds_multiple = st.number_input("Odds multiple", value=5, min_value=1,
                                    max_value=100, step=1)

    run = False
    load_watch = False
    if mode == "Simulate":
        st.subheader("Simulation")
        rolls = st.number_input("Rolls per session", value=5000, min_value=100,
                                max_value=200_000, step=1000)
        sessions = st.number_input("Sessions", value=200, min_value=10,
                                   max_value=5000, step=50)
        seed = st.number_input("Seed (0 = random)", value=0, min_value=0, step=1)
        workers = st.number_input("Workers (0 = all CPUs)", value=4, min_value=0,
                                  max_value=os.cpu_count() or 8, step=1)
        run = st.button("▶ Run simulation", type="primary",
                        use_container_width=True)
    else:
        st.subheader("Watch")
        w_seed = st.number_input("Seed", value=42, min_value=0, step=1,
                                 help="Same seed = same session, every time.")
        w_rolls = st.number_input("Rolls", value=300, min_value=10,
                                  max_value=5000, step=50)
        w_stop_loss = st.number_input("Stop-loss (0 = off)", value=0.0,
                                      min_value=0.0, max_value=1.0, step=0.05,
                                      help="End session at this fraction of "
                                           "the starting bankroll.")
        w_stop_win = st.number_input("Stop-win (0 = off)", value=0.0,
                                     min_value=0.0, step=0.5,
                                     help="End session at this multiple of "
                                          "the starting bankroll.")
        load_watch = st.button("🎬 Load session", type="primary",
                               use_container_width=True)

# ------------------------------------------------------------------ results --
if mode == "Simulate" and run:
    config = SimConfig(
        game=game,
        strategy=strategy_name,
        strategy_params=params,
        bankroll=bankroll,
        table=TableConfig(min_bet=min_bet, max_bet=max_bet,
                           odds_multiple=int(odds_multiple)),
        rolls=int(rolls),
        sessions=int(sessions),
        seed=int(seed) if seed else None,
        workers=int(workers),
    )
    with st.spinner(f"Simulating {int(sessions)} sessions × {int(rolls)} rolls..."):
        report = run_simulation(config)

    st.header(f"Results — {strategy_name}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Median final bankroll", f"${report.median_final:,.0f}",
              f"${report.median_final - bankroll:+,.0f} vs start")
    m2.metric("Realized house edge", f"{report.realized_edge:.2%}",
              "per $ wagered")
    m3.metric("Session win rate", f"{report.win_rate:.1%}")
    m4.metric("Risk of ruin", f"{report.ruin_rate:.1%}")

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Mean net profit", f"${report.mean_profit:+,.0f}")
    m6.metric("Mean max drawdown", f"${report.mean_max_drawdown:,.0f}")
    m7.metric("Total action", f"${report.total_action:,.0f}")
    m8.metric("p5 / p95 final", f"${report.p5_final:,.0f} / ${report.p95_final:,.0f}")

    # Percentile bands over time.
    xs = np.linspace(0, int(rolls), len(report.bands["p50"]))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=report.bands["p95"], mode="lines",
                             line=dict(width=0), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=xs, y=report.bands["p5"], mode="lines",
                             line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(99,110,250,0.15)", showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=xs, y=report.bands["p75"], mode="lines",
                             line=dict(width=0), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=xs, y=report.bands["p25"], mode="lines",
                             line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(99,110,250,0.25)",
                             name="p25–p75"))
    fig.add_trace(go.Scatter(x=xs, y=report.bands["p50"], mode="lines",
                             line=dict(color="#636EFA", width=2.5),
                             name="Median"))
    fig.add_hline(y=bankroll, line_dash="dash", line_color="gray",
                  annotation_text="starting bankroll")
    fig.update_layout(title="Bankroll over time (percentile bands across sessions)",
                      xaxis_title="Rolls", yaxis_title="Bankroll ($)",
                      hovermode="x unified", height=420)
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Reading the chart: the median line is the typical session; the bands "
        "show where the middle 50% (and 90%) of sessions end up. A downward "
        "slope is the house edge grinding — the steeper, the worse the strategy."
    )
elif mode == "Simulate":
    st.info("Configure a strategy in the sidebar, then hit **Run simulation**.")
    st.markdown(
        """
**What you can do here**

- Pick a strategy (or write your own in `src/portroyale/strategies/`) and
  tune its parameters.
- Monte Carlo it over hundreds of sessions and thousands of rolls.
- Compare the *realized* house edge, risk of ruin and drawdown across
  strategies — the numbers that decide whether a system survives contact
  with the tables.

Try `presser` vs `passline_odds`: does pressing after wins beat flat betting?
(The math says no — run it and see why.)
        """
    )

# -------------------------------------------------------------------- watch --
def _watch_key() -> tuple:
    return (game, strategy_name, tuple(sorted(params.items())), bankroll,
            min_bet, max_bet, odds_multiple, w_seed, w_rolls,
            w_stop_loss, w_stop_win)


def _load_watch_events() -> list[dict]:
    return list(watch_session(
        game=game,
        strategy=strategy_name,
        seed=int(w_seed),
        bankroll=float(bankroll),
        rolls=int(w_rolls),
        stop_loss=float(w_stop_loss) if w_stop_loss > 0 else None,
        stop_win=float(w_stop_win) if w_stop_win > 0 else None,
        params=params,
        min_bet=float(min_bet),
        max_bet=float(max_bet),
        odds_multiple=int(odds_multiple),
    ))


def _watch_feed(events: list[dict], upto_roll: int, n_rolls: int = 8) -> str:
    """Render the most recent rolls as a plain-text play-by-play."""
    blocks: dict[int, list[str]] = {}
    order: list[int] = []
    header: dict[int, str] = {}
    bankroll_line: dict[int, str] = {}
    for ev in events:
        t = ev["type"]
        if t == "roll" and ev["roll"] <= upto_roll:
            r = ev["roll"]
            point = f", point {ev['point']}" if ev["point"] else ""
            header[r] = f"[{r}] {ev['phase']}{point}: {ev['d1']}-{ev['d2']} = {ev['total']}"
            order.append(r)
        elif t == "bet_placed" and ev["roll"] <= upto_roll:
            num = f" on {ev['number']}" if ev["number"] else ""
            blocks.setdefault(ev["roll"], []).append(
                f"placed {ev['kind']}{num} ${ev['amount']:,.2f}")
        elif t == "bet_resolved" and ev["roll"] <= upto_roll:
            num = f" {ev['number']}" if ev["number"] else ""
            blocks.setdefault(ev["roll"], []).append(
                f"{ev['kind']}{num} ${ev['amount']:,.2f} → {ev['outcome']} "
                f"({ev['profit']:+,.2f})")
        elif t == "bankroll" and ev["roll"] <= upto_roll:
            bankroll_line[ev["roll"]] = f"bankroll ${ev['bankroll']:,.2f}"
    lines = []
    for r in order[-n_rolls:]:
        lines.append(header[r])
        for b in blocks.get(r, []):
            lines.append(f"    {b}")
        if r in bankroll_line:
            lines.append(f"    {bankroll_line[r]}")
    return "\n".join(lines) if lines else "No rolls yet — hit **Step** or **Auto-play**."


if mode == "Watch":
    st.header(f"Watch — {strategy_name} (seed {int(w_seed)})")

    key = _watch_key()
    state = st.session_state.get("watch")
    if load_watch or state is None or state.get("key") != key:
        with st.spinner("Dealing the session..."):
            events = _load_watch_events()
        st.session_state["watch"] = {"key": key, "events": events, "roll": 0}
        state = st.session_state["watch"]

    events = state["events"]
    max_roll = max((ev["roll"] for ev in events if ev["type"] == "bankroll"),
                   default=0)
    end_ev = next((ev for ev in events if ev["type"] == "session_end"), None)

    c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
    step = c1.button("⏭ Step", use_container_width=True)
    autoplay = c2.checkbox("▶ Auto-play")
    speed = c3.slider("Rolls/sec", 1, 20, 4,
                      help="Auto-play speed", label_visibility="collapsed")
    new_roll = c4.slider("Roll", 0, max_roll, state["roll"],
                         help="Scrub through the session")

    if step:
        state["roll"] = min(max_roll, state["roll"] + 1)
    else:
        state["roll"] = new_roll
    if autoplay and state["roll"] < max_roll:
        state["roll"] += 1
        time.sleep(1.0 / speed)
        st.rerun()

    upto = state["roll"]
    series = [(ev["roll"], ev["bankroll"]) for ev in events
              if ev["type"] == "bankroll" and ev["roll"] <= upto]
    if series:
        xs, ys = zip(*series)
        fig = go.Figure(go.Scatter(x=list(xs), y=list(ys), mode="lines",
                                   line=dict(color="#636EFA", width=2)))
        fig.add_hline(y=bankroll, line_dash="dash", line_color="gray",
                      annotation_text="start")
        end_x = max_roll if max_roll else int(w_rolls)
        fig.update_layout(title="Bankroll as the session plays out",
                          xaxis_title="Roll", yaxis_title="Bankroll ($)",
                          xaxis=dict(range=[0, end_x]),
                          height=320, margin=dict(t=40, b=40))
        st.plotly_chart(fig, use_container_width=True)

    if end_ev is not None and upto >= end_ev["rolls_played"]:
        st.success(f"Session over after {end_ev['rolls_played']} rolls "
                   f"({end_ev['reason']}) — final "
                   f"${end_ev['final_bankroll']:,.2f} "
                   f"({end_ev['net_profit']:+,.2f}). "
                   f"Replay it any time: same strategy + seed {int(w_seed)}.")

    st.subheader("Play-by-play")
    st.code(_watch_feed(events, upto), language=None)

    st.caption(
        "This feed is the engine's event stream — the same JSON-serializable "
        "events the future mobile table will render (see `docs/watch-mode.md`). "
        "Same seed always replays the identical session."
    )
