import numpy as np
import pandas as pd
from langchain_core.tools import tool

@tool
def python_repl(ticker: str, lookback_days: int = 252) -> str:
    """Fetch OHLCV data and compute annualized volatility and momentum."""
    # Dummy implementation for schema purposes
    return f"ticker={ticker} volatility=0.32 momentum=0.07"
