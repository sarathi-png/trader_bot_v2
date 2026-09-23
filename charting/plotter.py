"""
Signal chart generation using mplfinance.
Creates annotated candlestick charts with support/resistance, SL/TP levels.
"""

import matplotlib

# Headless rendering: HuggingFace Spaces / Docker containers have no display.
# Must be set before matplotlib.pyplot (imported by mplfinance) is imported.
matplotlib.use("Agg")

import pandas as pd
import numpy as np
import mplfinance as mpf
from pathlib import Path
from typing import Optional, Dict, Any


def generate_signal_chart(
    df: pd.DataFrame,
    support: Optional[float] = None,
    resistance: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    entry: Optional[float] = None,
    signal: str = "",
    symbol: str = "",
    output_path: str = "signal.png",
    hlines_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate a candlestick chart with S/R zones and SL/TP levels.

    Creates a professional trading signal chart with:
    - Candlestick pattern (OHLC)
    - Horizontal lines for support (green), resistance (red)
    - SL level (red dashed), TP level (green dashed)
    - Entry level (blue)
    - Optional volume subplot

    Args:
        df: DataFrame with [open, high, low, close, volume] and datetime index
        support: Support zone price level (green line)
        resistance: Resistance zone price level (red line)
        sl: Stop loss level (red dashed line)
        tp: Take profit level (green dashed line)
        entry: Entry price level (blue line)
        signal: Signal type ('BUY' or 'SELL') for title
        symbol: Trading symbol for chart title
        output_path: File path for saving the chart image
        hlines_config: Optional custom hlines configuration dict

    Returns:
        Path to the saved chart image

    Raises:
        ValueError: If DataFrame doesn't have required columns or index
    """
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"DataFrame must contain columns: {required}")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be DatetimeIndex")

    # Prepare horizontal lines data
    hlines_prices = []
    hlines_colors = []
    hlines_styles = []
    hlines_widths = []

    # Support line (green, solid)
    if support is not None:
        hlines_prices.append(support)
        hlines_colors.append("#2ecc71")  # Green
        hlines_styles.append("-")
        hlines_widths.append(2)

    # Resistance line (red, solid)
    if resistance is not None:
        hlines_prices.append(resistance)
        hlines_colors.append("#e74c3c")  # Red
        hlines_styles.append("-")
        hlines_widths.append(2)

    # Entry line (blue, solid)
    if entry is not None:
        hlines_prices.append(entry)
        hlines_colors.append("#3498db")  # Blue
        hlines_styles.append("-")
        hlines_widths.append(1.5)

    # SL line (red, dashed)
    if sl is not None:
        hlines_prices.append(sl)
        hlines_colors.append("#c0392b")  # Dark red
        hlines_styles.append("--")
        hlines_widths.append(1.5)

    # TP line (green, dashed)
    if tp is not None:
        hlines_prices.append(tp)
        hlines_colors.append("#27ae60")  # Dark green
        hlines_styles.append("--")
        hlines_widths.append(1.5)

    # Create hlines kwargs
    hlines_kwargs = {}
    if hlines_prices:
        hlines_kwargs = {
            "hlines": dict(
                hlines=hlines_prices,
                colors=hlines_colors,
                linestyle=hlines_styles,
                linewidths=hlines_widths,
            )
        }

    # Custom hlines override
    if hlines_config:
        hlines_kwargs.update(hlines_config)

    # Title
    title = f"{symbol} | {signal} Signal" if signal else f"{symbol} Chart"

    # Style configuration
    mc = mpf.make_marketcolors(
        up="#2ecc71",     # Green for bullish candles
        down="#e74c3c",   # Red for bearish candles
        edge="inherit",
        wick="inherit",
        volume="inherit",
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        gridstyle=":",
        gridcolor="#ecf0f1",
        rc={
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
        },
    )

    # Ensure output directory exists
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate chart
    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        title=title,
        ylabel="Price",
        volume="volume" in df.columns,
        figsize=(14, 8),
        tight_layout=True,
        returnfig=True,
        **hlines_kwargs,
    )

    # Add legend if we have lines
    if hlines_prices:
        from matplotlib.lines import Line2D
        legend_elements = []

        if support is not None:
            legend_elements.append(
                Line2D([0], [0], color="#2ecc71", linewidth=2, label=f"Support: {support:.2f}")
            )
        if resistance is not None:
            legend_elements.append(
                Line2D([0], [0], color="#e74c3c", linewidth=2, label=f"Resistance: {resistance:.2f}")
            )
        if entry is not None:
            legend_elements.append(
                Line2D([0], [0], color="#3498db", linewidth=1.5, label=f"Entry: {entry:.2f}")
            )
        if sl is not None:
            legend_elements.append(
                Line2D([0], [0], color="#c0392b", linewidth=1.5, linestyle="--", label=f"SL: {sl:.2f}")
            )
        if tp is not None:
            legend_elements.append(
                Line2D([0], [0], color="#27ae60", linewidth=1.5, linestyle="--", label=f"TP: {tp:.2f}")
            )

        axes[0].legend(
            handles=legend_elements,
            loc="upper left",
            fontsize=9,
            framealpha=0.8,
        )

    # Save chart
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)

    return str(output_path)
