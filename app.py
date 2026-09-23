"""Port Royale — Streamlit strategy lab.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import os

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from portroyale import __version__
from portroyale.games import list_games
from portroyale.sim import SimConfig, TableConfig, run_simulation
from portroyale.strategies import STRATEGIES, list_strategies

st.set_page_config(page_title="Port Royale", page_icon="🎲", layout="wide")
st.title("🎲 Port Royale — Casino Strategy Lab")
st.caption(f"v{__version__} · define a strategy, Monte Carlo it, see the math")

# ---------------------------------------------------------------- sidebar ---
with st.sidebar:
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

    st.subheader("Simulation")
    rolls = st.number_input("Rolls per session", value=5000, min_value=100,
                            max_value=200_000, step=1000)
    sessions = st.number_input("Sessions", value=200, min_value=10,
                               max_value=5000, step=50)
    seed = st.number_input("Seed (0 = random)", value=0, min_value=0, step=1)
    workers = st.number_input("Workers (0 = all CPUs)", value=4, min_value=0,
                              max_value=os.cpu_count() or 8, step=1)

    run = st.button("▶ Run simulation", type="primary", use_container_width=True)

# ------------------------------------------------------------------ results --
if run:
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
else:
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
