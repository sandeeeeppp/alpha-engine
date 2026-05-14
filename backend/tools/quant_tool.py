import numpy as np
import yfinance as yf
from langchain_core.tools import tool


@tool
def python_repl(ticker: str, lookback_days: int = 252) -> str:
    """
    Fetches 1-year daily OHLCV data for a given ticker and computes
    annualized volatility and momentum. Returns a structured string
    containing the computed metrics for downstream synthesis.
    """
    try:
        ticker = ticker.strip().upper()
        df = yf.download(
            ticker,
            period="1y",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )

        if df.empty or len(df) < 50:
            return (
                f"[QUANT] ERROR: Insufficient market data for {ticker}. "
                f"Symbol may be invalid or delisted."
            )

        close = df["Close"].squeeze()
        daily_returns = close.pct_change().dropna()

        if len(daily_returns) < 20:
            return f"[QUANT] ERROR: Not enough return data for {ticker}."

        annualized_volatility = float(daily_returns.std() * np.sqrt(252))
        momentum_90d = float(
            (close.iloc[-1] / close.iloc[-min(90, len(close))]) - 1
        )
        current_price = float(close.iloc[-1])

        return (
            f"[QUANT] Ticker: {ticker} | "
            f"Price: ${current_price:.2f} | "
            f"Annualized Volatility: {annualized_volatility:.4f} | "
            f"90-Day Momentum: {momentum_90d:.4f}"
        )
    except Exception as e:
        return f"[QUANT] ERROR: Data acquisition failed for {ticker}: {str(e)}"
