"""Port Royale — a casino game strategy builder and Monte Carlo simulator."""

__version__ = "0.1.0"

from .games import make_table
from .sim import SimConfig, run_simulation
from .strategies import make_strategy

__all__ = ["__version__", "make_strategy", "make_table", "SimConfig", "run_simulation"]
