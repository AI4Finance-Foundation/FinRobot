#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  ███████╗██╗███╗   ██╗██████╗  ██████╗ ██████╗  ██████╗ ████████╗            ║
║  ██╔════╝██║████╗  ██║██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗╚══██╔══╝            ║
║  █████╗  ██║██╔██╗ ██║██████╔╝██║   ██║██████╔╝██║   ██║   ██║               ║
║  ██╔══╝  ██║██║╚██╗██║██╔══██╗██║   ██║██╔══██╗██║   ██║   ██║               ║
║  ██║     ██║██║ ╚████║██║  ██║╚██████╔╝██████╔╝╚██████╔╝   ██║               ║
║  ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝    ╚═╝               ║
║                                                                               ║
║  ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀ ║
║  CYBERPUNK FINANCIAL TERMINAL v1.0                                            ║
║  Bloomberg Terminal meets Cyberpunk 2077                                      ║
╚═══════════════════════════════════════════════════════════════════════════════╝

A high-aesthetic TUI dashboard for visualizing FinRobot agent activities,
real-time market data, and trading signals.

Usage:
    python finrobot_terminal_ui.py --demo    # Run with simulated data
    python finrobot_terminal_ui.py           # Run (waiting for real agent data)

Author: FinRobot Contributors
License: MIT
"""

from __future__ import annotations

import argparse
import asyncio
import random
from collections import deque
from datetime import datetime
from typing import Optional, Callable, Any
from queue import Queue

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Log, ProgressBar, Footer, Header
from textual.timer import Timer
from textual import work

from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.console import Console, Group
from rich.align import Align


# ═══════════════════════════════════════════════════════════════════════════════
# CYBERPUNK COLOR SCHEME
# ═══════════════════════════════════════════════════════════════════════════════

NEON_GREEN = "#00ff00"
NEON_AMBER = "#ffb000"
NEON_CYAN = "#00ffff"
NEON_MAGENTA = "#ff00ff"
NEON_RED = "#ff3333"
DARK_BG = "#0a0a0a"
PANEL_BG = "#111111"
BORDER_COLOR = "#333333"


# ═══════════════════════════════════════════════════════════════════════════════
# CSS STYLESHEET - THE CYBERPUNK AESTHETIC
# ═══════════════════════════════════════════════════════════════════════════════

CYBERPUNK_CSS = """
Screen {
    background: #0a0a0a;
}

#main-grid {
    layout: grid;
    grid-size: 3 2;
    grid-columns: 1fr 2fr 1fr;
    grid-rows: auto 1fr;
    padding: 0;
    margin: 0;
}

#ticker-bar {
    column-span: 3;
    height: 3;
    background: #111111;
    border: solid #333333;
    padding: 0 1;
}

#market-panel {
    background: #111111;
    border: solid #00ff00;
    padding: 1;
    margin: 0 1;
}

#neural-panel {
    background: #111111;
    border: solid #ffb000;
    padding: 1;
    margin: 0;
}

#signal-panel {
    background: #111111;
    border: solid #00ffff;
    padding: 1;
    margin: 0 1;
}

.panel-title {
    text-style: bold;
    color: #00ff00;
    text-align: center;
    padding: 0 0 1 0;
}

#neural-log {
    background: #0a0a0a;
    color: #00ff00;
    border: none;
    scrollbar-color: #00ff00;
    scrollbar-color-hover: #00ff00;
    scrollbar-color-active: #ffb000;
}

#neural-log:focus {
    border: none;
}

.metric-label {
    color: #888888;
}

.metric-value {
    color: #00ff00;
    text-style: bold;
}

.signal-buy {
    color: #00ff00;
    text-style: bold;
}

.signal-sell {
    color: #ff3333;
    text-style: bold;
}

.signal-hold {
    color: #ffb000;
    text-style: bold;
}

#confidence-bar {
    margin: 1 0;
}

#confidence-bar > .bar--bar {
    color: #00ff00;
}

#confidence-bar > .bar--complete {
    color: #00ff00;
}

Footer {
    background: #111111;
    color: #00ff00;
}

Header {
    background: #111111;
    color: #00ff00;
}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# DEMO DATA GENERATOR - SIMULATED MARKET & AGENT ACTIVITY
# ═══════════════════════════════════════════════════════════════════════════════

class DemoDataGenerator:
    """Generates realistic fake data streams for demo mode."""

    STOCKS = {
        "NVDA": {"price": 140.0, "volatility": 0.02},
        "AAPL": {"price": 185.0, "volatility": 0.01},
        "MSFT": {"price": 420.0, "volatility": 0.015},
        "GOOGL": {"price": 175.0, "volatility": 0.018},
        "TSLA": {"price": 250.0, "volatility": 0.03},
        "BTC": {"price": 95000.0, "volatility": 0.025},
        "ETH": {"price": 3200.0, "volatility": 0.028},
    }

    NEURAL_THOUGHTS = [
        ("INIT", "Neural network initialized. Loading market context..."),
        ("DATA", "Fetching real-time price feeds from primary sources..."),
        ("DATA", "Cross-referencing with SEC filings database..."),
        ("PARSE", "Extracting key financial metrics from 10-K report..."),
        ("PARSE", "Processing earnings call transcript (Q4 2024)..."),
        ("NLP", "Running sentiment analysis on management commentary..."),
        ("NLP", "Detected POSITIVE sentiment score: {:.2f}".format(random.uniform(0.7, 0.95))),
        ("QUANT", "Computing 50-day moving average crossover..."),
        ("QUANT", "RSI indicator shows OVERSOLD conditions..."),
        ("QUANT", "MACD histogram turning positive..."),
        ("RISK", "Evaluating portfolio exposure limits..."),
        ("RISK", "VaR calculation within acceptable bounds..."),
        ("STRATEGY", "Pattern detected: GOLDEN CROSS formation"),
        ("STRATEGY", "Historical backtest confidence: 78.5%"),
        ("MEMORY", "Retrieving similar market conditions from 2021-Q4..."),
        ("MEMORY", "Context similarity score: 0.89"),
        ("REASON", "Bullish divergence confirmed on daily timeframe..."),
        ("REASON", "Institutional flow analysis: NET BUYING pressure"),
        ("SIGNAL", "Generating trading signal with confidence interval..."),
        ("EXECUTE", "Signal validated. Preparing recommendation..."),
    ]

    SIGNALS = ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]
    SIGNAL_WEIGHTS = [0.15, 0.25, 0.30, 0.20, 0.10]

    def __init__(self):
        self.price_history: dict[str, deque] = {
            ticker: deque(maxlen=50) for ticker in self.STOCKS
        }
        self.current_prices = {t: s["price"] for t, s in self.STOCKS.items()}
        self._init_price_history()
        self.thought_index = 0

    def _init_price_history(self):
        """Initialize price history with random walk."""
        for ticker, config in self.STOCKS.items():
            price = config["price"]
            for _ in range(50):
                change = random.gauss(0, config["volatility"]) * price
                price = max(price + change, price * 0.5)
                self.price_history[ticker].append(price)
            self.current_prices[ticker] = price

    def tick_prices(self) -> dict[str, tuple[float, float]]:
        """Generate next price tick. Returns {ticker: (price, change%)}."""
        results = {}
        for ticker, config in self.STOCKS.items():
            old_price = self.current_prices[ticker]
            change = random.gauss(0, config["volatility"]) * old_price
            new_price = max(old_price + change, old_price * 0.5)
            self.current_prices[ticker] = new_price
            self.price_history[ticker].append(new_price)
            pct_change = ((new_price - old_price) / old_price) * 100
            results[ticker] = (new_price, pct_change)
        return results

    def get_neural_thought(self) -> tuple[str, str]:
        """Get next agent thought for neural stream."""
        # Cycle through thoughts with some randomness
        if random.random() < 0.3:
            thought = random.choice(self.NEURAL_THOUGHTS)
        else:
            thought = self.NEURAL_THOUGHTS[self.thought_index % len(self.NEURAL_THOUGHTS)]
            self.thought_index += 1
        return thought

    def generate_signal(self) -> tuple[str, float]:
        """Generate trading signal with confidence."""
        signal = random.choices(self.SIGNALS, weights=self.SIGNAL_WEIGHTS)[0]
        if signal in ("STRONG BUY", "STRONG SELL"):
            confidence = random.uniform(0.85, 0.98)
        elif signal in ("BUY", "SELL"):
            confidence = random.uniform(0.65, 0.85)
        else:
            confidence = random.uniform(0.45, 0.65)
        return signal, confidence

    def get_metrics(self, ticker: str = "NVDA") -> dict[str, Any]:
        """Generate fake technical metrics."""
        return {
            "P/E Ratio": f"{random.uniform(20, 80):.1f}",
            "RSI (14)": f"{random.uniform(25, 75):.1f}",
            "MACD": f"{random.uniform(-5, 5):.2f}",
            "Volume": f"{random.randint(10, 100)}M",
            "52W High": f"${self.current_prices[ticker] * random.uniform(1.1, 1.3):.2f}",
            "52W Low": f"${self.current_prices[ticker] * random.uniform(0.5, 0.8):.2f}",
            "Avg Vol": f"{random.randint(30, 80)}M",
            "Beta": f"{random.uniform(0.8, 2.0):.2f}",
        }

    def get_price_chart_data(self, ticker: str = "NVDA") -> list[float]:
        """Get price history for ASCII chart."""
        return list(self.price_history.get(ticker, []))


# ═══════════════════════════════════════════════════════════════════════════════
# ASCII CHART RENDERER
# ═══════════════════════════════════════════════════════════════════════════════

def render_ascii_chart(
    data: list[float],
    width: int = 40,
    height: int = 10,
    color: str = NEON_GREEN
) -> Text:
    """Render an ASCII sparkline chart with Rich styling."""
    if not data or len(data) < 2:
        return Text("[ NO DATA ]", style=f"dim {color}")

    # Normalize data to fit height
    min_val, max_val = min(data), max(data)
    val_range = max_val - min_val if max_val != min_val else 1

    # Resample data to fit width
    if len(data) > width:
        step = len(data) / width
        data = [data[int(i * step)] for i in range(width)]

    # Build chart
    chart_chars = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    lines = []

    for val in data:
        normalized = (val - min_val) / val_range
        char_idx = min(int(normalized * (len(chart_chars) - 1)), len(chart_chars) - 1)
        lines.append(chart_chars[char_idx])

    # Create Rich Text with gradient effect
    text = Text()
    for i, char in enumerate(lines):
        # Color gradient from amber to green based on position
        if i < len(lines) * 0.3:
            text.append(char, style=NEON_AMBER)
        elif i < len(lines) * 0.7:
            text.append(char, style=NEON_GREEN)
        else:
            text.append(char, style=NEON_CYAN)

    # Add price labels
    result = Text()
    result.append(f"${max_val:,.0f}\n", style="dim white")
    result.append(text)
    result.append(f"\n${min_val:,.0f}", style="dim white")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM WIDGETS
# ═══════════════════════════════════════════════════════════════════════════════

class TickerBar(Static):
    """Scrolling marquee showing live stock prices."""

    ticker_text = reactive("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prices: dict[str, tuple[float, float]] = {}
        self.scroll_pos = 0

    def update_prices(self, prices: dict[str, tuple[float, float]]):
        """Update prices and refresh display."""
        self.prices = prices
        self._build_ticker()

    def _build_ticker(self):
        """Build the ticker text."""
        text = Text()
        text.append("  ◆ ", style=f"bold {NEON_GREEN}")
        text.append("FINROBOT LIVE", style=f"bold {NEON_GREEN}")
        text.append("  │  ", style="dim")

        for ticker, (price, change) in self.prices.items():
            text.append(f"{ticker} ", style="bold white")

            # Format price based on magnitude
            if price >= 1000:
                price_str = f"${price/1000:.1f}K"
            else:
                price_str = f"${price:.2f}"

            text.append(price_str, style="white")

            # Change indicator
            if change >= 0:
                text.append(f" ▲{change:.1f}%", style=f"bold {NEON_GREEN}")
            else:
                text.append(f" ▼{abs(change):.1f}%", style=f"bold {NEON_RED}")

            text.append("  │  ", style="dim")

        # Add timestamp
        now = datetime.now().strftime("%H:%M:%S")
        text.append(f"⏱ {now}", style=f"dim {NEON_AMBER}")

        self.update(text)


class MarketPanel(Static):
    """Left panel showing market data and ASCII chart."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.chart_data: list[float] = []
        self.metrics: dict[str, str] = {}
        self.current_ticker = "NVDA"

    def update_data(self, chart_data: list[float], metrics: dict[str, str], ticker: str = "NVDA"):
        """Update market data and refresh."""
        self.chart_data = chart_data
        self.metrics = metrics
        self.current_ticker = ticker
        self._render()

    def _render(self):
        """Render the market panel."""
        # Title
        title = Text()
        title.append("╔══════════════════════════╗\n", style=NEON_GREEN)
        title.append("║   ", style=NEON_GREEN)
        title.append("📊 MARKET WATCH", style=f"bold {NEON_GREEN}")
        title.append("    ║\n", style=NEON_GREEN)
        title.append("╚══════════════════════════╝\n\n", style=NEON_GREEN)

        # Ticker name
        title.append(f"  [{self.current_ticker}]", style=f"bold {NEON_CYAN}")
        if self.chart_data:
            current = self.chart_data[-1] if self.chart_data else 0
            title.append(f"  ${current:,.2f}\n\n", style="bold white")

        # ASCII Chart
        chart = render_ascii_chart(self.chart_data, width=35, height=8)

        # Metrics table
        metrics_text = Text("\n\n")
        metrics_text.append("─" * 28 + "\n", style="dim")
        metrics_text.append("  KEY METRICS\n", style=f"bold {NEON_AMBER}")
        metrics_text.append("─" * 28 + "\n", style="dim")

        for key, value in self.metrics.items():
            metrics_text.append(f"  {key:<12}", style="dim white")
            # Color value based on content
            if "%" in value or value.startswith("$"):
                metrics_text.append(f"{value:>10}\n", style=f"bold {NEON_GREEN}")
            else:
                metrics_text.append(f"{value:>10}\n", style="white")

        # Combine all
        result = Text()
        result.append_text(title)
        result.append_text(chart)
        result.append_text(metrics_text)

        self.update(result)


class NeuralStream(ScrollableContainer):
    """Center panel showing agent's chain of thought."""

    def compose(self) -> ComposeResult:
        yield Static(self._render_header(), id="neural-header")
        yield Log(id="neural-log", highlight=True, markup=True)

    def _render_header(self) -> Text:
        """Render the panel header."""
        text = Text()
        text.append("╔════════════════════════════════════════════╗\n", style=NEON_AMBER)
        text.append("║   ", style=NEON_AMBER)
        text.append("🧠 NEURAL STREAM", style=f"bold {NEON_AMBER}")
        text.append(" - Agent Cognition   ║\n", style=NEON_AMBER)
        text.append("╚════════════════════════════════════════════╝", style=NEON_AMBER)
        return text

    def add_thought(self, category: str, message: str):
        """Add a new thought to the neural stream."""
        log = self.query_one("#neural-log", Log)

        # Format based on category
        category_colors = {
            "INIT": NEON_CYAN,
            "DATA": "white",
            "PARSE": NEON_GREEN,
            "NLP": NEON_MAGENTA,
            "QUANT": NEON_AMBER,
            "RISK": NEON_RED,
            "STRATEGY": NEON_GREEN,
            "MEMORY": NEON_CYAN,
            "REASON": NEON_AMBER,
            "SIGNAL": NEON_GREEN,
            "EXECUTE": f"bold {NEON_GREEN}",
        }

        color = category_colors.get(category, NEON_GREEN)
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Format the log line
        log.write_line(f"[dim]{timestamp}[/dim] [{color}][{category:^8}][/{color}] {message}")


class SignalPanel(Static):
    """Right panel showing trading signal and confidence."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.signal = "ANALYZING"
        self.confidence = 0.0

    def update_signal(self, signal: str, confidence: float):
        """Update signal and confidence."""
        self.signal = signal
        self.confidence = confidence
        self._render()

    def _render(self):
        """Render the signal panel."""
        # Title
        text = Text()
        text.append("╔══════════════════════════╗\n", style=NEON_CYAN)
        text.append("║   ", style=NEON_CYAN)
        text.append("⚡ SIGNAL OUTPUT", style=f"bold {NEON_CYAN}")
        text.append("   ║\n", style=NEON_CYAN)
        text.append("╚══════════════════════════╝\n\n", style=NEON_CYAN)

        # Signal display
        signal_art = self._get_signal_art()
        text.append_text(signal_art)

        # Confidence bar
        text.append("\n\n")
        text.append("  CONFIDENCE LEVEL\n", style="dim white")
        text.append("  ", style="")

        # ASCII progress bar
        bar_width = 20
        filled = int(self.confidence * bar_width)
        empty = bar_width - filled

        if self.signal in ("STRONG BUY", "BUY"):
            bar_color = NEON_GREEN
        elif self.signal in ("STRONG SELL", "SELL"):
            bar_color = NEON_RED
        else:
            bar_color = NEON_AMBER

        text.append("█" * filled, style=bar_color)
        text.append("░" * empty, style="dim")
        text.append(f" {self.confidence*100:.0f}%\n", style=f"bold {bar_color}")

        # Analysis status
        text.append("\n")
        text.append("─" * 26 + "\n", style="dim")
        text.append("  STATUS: ", style="dim white")
        text.append("● LIVE\n", style=f"bold {NEON_GREEN}")
        text.append("  AGENT: ", style="dim white")
        text.append("FinRobot-v1\n", style="white")
        text.append("  MODEL: ", style="dim white")
        text.append("GPT-4 Turbo\n", style="white")

        self.update(text)

    def _get_signal_art(self) -> Text:
        """Get ASCII art for the signal."""
        text = Text()

        if self.signal == "STRONG BUY":
            text.append("   ╔═══════════════════╗\n", style=NEON_GREEN)
            text.append("   ║                   ║\n", style=NEON_GREEN)
            text.append("   ║   ", style=NEON_GREEN)
            text.append("STRONG BUY", style=f"bold {NEON_GREEN} on black")
            text.append("   ║\n", style=NEON_GREEN)
            text.append("   ║       ▲▲▲         ║\n", style=NEON_GREEN)
            text.append("   ╚═══════════════════╝", style=NEON_GREEN)

        elif self.signal == "BUY":
            text.append("   ╔═══════════════════╗\n", style=NEON_GREEN)
            text.append("   ║                   ║\n", style=NEON_GREEN)
            text.append("   ║       ", style=NEON_GREEN)
            text.append("BUY", style=f"bold {NEON_GREEN} on black")
            text.append("       ║\n", style=NEON_GREEN)
            text.append("   ║        ▲          ║\n", style=NEON_GREEN)
            text.append("   ╚═══════════════════╝", style=NEON_GREEN)

        elif self.signal == "STRONG SELL":
            text.append("   ╔═══════════════════╗\n", style=NEON_RED)
            text.append("   ║                   ║\n", style=NEON_RED)
            text.append("   ║  ", style=NEON_RED)
            text.append("STRONG SELL", style=f"bold {NEON_RED} on black")
            text.append("   ║\n", style=NEON_RED)
            text.append("   ║       ▼▼▼         ║\n", style=NEON_RED)
            text.append("   ╚═══════════════════╝", style=NEON_RED)

        elif self.signal == "SELL":
            text.append("   ╔═══════════════════╗\n", style=NEON_RED)
            text.append("   ║                   ║\n", style=NEON_RED)
            text.append("   ║      ", style=NEON_RED)
            text.append("SELL", style=f"bold {NEON_RED} on black")
            text.append("       ║\n", style=NEON_RED)
            text.append("   ║        ▼          ║\n", style=NEON_RED)
            text.append("   ╚═══════════════════╝", style=NEON_RED)

        elif self.signal == "HOLD":
            text.append("   ╔═══════════════════╗\n", style=NEON_AMBER)
            text.append("   ║                   ║\n", style=NEON_AMBER)
            text.append("   ║      ", style=NEON_AMBER)
            text.append("HOLD", style=f"bold {NEON_AMBER} on black")
            text.append("       ║\n", style=NEON_AMBER)
            text.append("   ║        ◆          ║\n", style=NEON_AMBER)
            text.append("   ╚═══════════════════╝", style=NEON_AMBER)

        else:  # ANALYZING
            text.append("   ╔═══════════════════╗\n", style="dim")
            text.append("   ║                   ║\n", style="dim")
            text.append("   ║   ", style="dim")
            text.append("ANALYZING...", style="dim italic")
            text.append("   ║\n", style="dim")
            text.append("   ║       ···         ║\n", style="dim")
            text.append("   ╚═══════════════════╝", style="dim")

        return text


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT DATA INTERFACE - For Real FinRobot Integration
# ═══════════════════════════════════════════════════════════════════════════════

class AgentDataInterface:
    """
    Interface for connecting real FinRobot agents to the TUI.

    Usage:
        interface = AgentDataInterface()

        # In your agent code:
        interface.push_thought("STRATEGY", "Detected bullish pattern")
        interface.push_signal("BUY", 0.85)
        interface.push_price("NVDA", 145.50)

        # In TUI:
        app = FinRobotTerminal(data_interface=interface)
    """

    def __init__(self):
        self.thought_queue: Queue = Queue()
        self.signal_queue: Queue = Queue()
        self.price_queue: Queue = Queue()
        self.metric_queue: Queue = Queue()

    def push_thought(self, category: str, message: str):
        """Push an agent thought to the UI."""
        self.thought_queue.put((category, message))

    def push_signal(self, signal: str, confidence: float):
        """Push a trading signal to the UI."""
        self.signal_queue.put((signal, confidence))

    def push_price(self, ticker: str, price: float, change_pct: float = 0.0):
        """Push a price update to the UI."""
        self.price_queue.put((ticker, price, change_pct))

    def push_metrics(self, ticker: str, metrics: dict[str, str]):
        """Push metric updates to the UI."""
        self.metric_queue.put((ticker, metrics))


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

class FinRobotTerminal(App):
    """
    The Cyberpunk Financial Terminal - A TUI for FinRobot.

    This provides a "Mission Control" interface for observing agent behavior,
    market data, and trading signals in real-time.
    """

    CSS = CYBERPUNK_CSS
    TITLE = "FINROBOT TERMINAL v1.0"
    SUB_TITLE = "Cyberpunk Financial Intelligence"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "toggle_dark", "Toggle Dark"),
        ("r", "refresh", "Refresh"),
        ("space", "toggle_pause", "Pause/Resume"),
    ]

    def __init__(
        self,
        demo_mode: bool = False,
        data_interface: Optional[AgentDataInterface] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.demo_mode = demo_mode
        self.data_interface = data_interface or AgentDataInterface()
        self.demo_generator = DemoDataGenerator() if demo_mode else None
        self.paused = False
        self._update_timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header(show_clock=True)

        with Container(id="main-grid"):
            # Top row - ticker bar spanning all columns
            yield TickerBar(id="ticker-bar")

            # Bottom row - three panels
            yield MarketPanel(id="market-panel")
            yield NeuralStream(id="neural-panel")
            yield SignalPanel(id="signal-panel")

        yield Footer()

    def on_mount(self):
        """Called when app is mounted - start data updates."""
        # Show startup message
        neural = self.query_one(NeuralStream)
        neural.add_thought("INIT", "FinRobot Terminal v1.0 initialized")
        neural.add_thought("INIT", f"Mode: {'DEMO' if self.demo_mode else 'LIVE'}")
        neural.add_thought("INIT", "Establishing neural link...")

        # Initialize displays
        if self.demo_mode:
            self._init_demo_display()

        # Start update loop
        self._update_timer = self.set_interval(0.5, self._update_loop)

    def _init_demo_display(self):
        """Initialize display with demo data."""
        if not self.demo_generator:
            return

        # Initialize ticker
        prices = self.demo_generator.tick_prices()
        ticker = self.query_one(TickerBar)
        ticker.update_prices(prices)

        # Initialize market panel
        market = self.query_one(MarketPanel)
        chart_data = self.demo_generator.get_price_chart_data("NVDA")
        metrics = self.demo_generator.get_metrics("NVDA")
        market.update_data(chart_data, metrics, "NVDA")

        # Initialize signal panel
        signal_panel = self.query_one(SignalPanel)
        signal_panel.update_signal("ANALYZING", 0.0)

    async def _update_loop(self):
        """Main update loop for data refresh."""
        if self.paused:
            return

        if self.demo_mode:
            await self._update_demo()
        else:
            await self._update_live()

    async def _update_demo(self):
        """Update with demo data."""
        if not self.demo_generator:
            return

        # Update ticker prices
        prices = self.demo_generator.tick_prices()
        ticker = self.query_one(TickerBar)
        ticker.update_prices(prices)

        # Update market panel occasionally
        if random.random() < 0.3:
            market = self.query_one(MarketPanel)
            chart_data = self.demo_generator.get_price_chart_data("NVDA")
            metrics = self.demo_generator.get_metrics("NVDA")
            market.update_data(chart_data, metrics, "NVDA")

        # Add neural thoughts
        if random.random() < 0.4:
            neural = self.query_one(NeuralStream)
            category, message = self.demo_generator.get_neural_thought()
            neural.add_thought(category, message)

        # Update signal occasionally
        if random.random() < 0.1:
            signal_panel = self.query_one(SignalPanel)
            signal, confidence = self.demo_generator.generate_signal()
            signal_panel.update_signal(signal, confidence)

            # Log the signal
            neural = self.query_one(NeuralStream)
            neural.add_thought("SIGNAL", f"Generated: {signal} (conf: {confidence:.1%})")

    async def _update_live(self):
        """Update with live data from interface."""
        # Process thought queue
        neural = self.query_one(NeuralStream)
        while not self.data_interface.thought_queue.empty():
            try:
                category, message = self.data_interface.thought_queue.get_nowait()
                neural.add_thought(category, message)
            except:
                break

        # Process signal queue
        signal_panel = self.query_one(SignalPanel)
        while not self.data_interface.signal_queue.empty():
            try:
                signal, confidence = self.data_interface.signal_queue.get_nowait()
                signal_panel.update_signal(signal, confidence)
            except:
                break

        # Process price queue
        ticker = self.query_one(TickerBar)
        prices = {}
        while not self.data_interface.price_queue.empty():
            try:
                t, price, change = self.data_interface.price_queue.get_nowait()
                prices[t] = (price, change)
            except:
                break
        if prices:
            ticker.update_prices(prices)

    def action_toggle_pause(self):
        """Toggle pause/resume."""
        self.paused = not self.paused
        neural = self.query_one(NeuralStream)
        if self.paused:
            neural.add_thought("SYSTEM", "⏸ Stream PAUSED")
        else:
            neural.add_thought("SYSTEM", "▶ Stream RESUMED")

    def action_refresh(self):
        """Force refresh all displays."""
        if self.demo_mode:
            self._init_demo_display()
        neural = self.query_one(NeuralStream)
        neural.add_thought("SYSTEM", "Display refreshed")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Main entry point for the FinRobot Terminal."""
    parser = argparse.ArgumentParser(
        description="FinRobot Cyberpunk Financial Terminal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  FINROBOT TERMINAL - Cyberpunk Financial Intelligence                         ║
║                                                                               ║
║  A high-aesthetic TUI dashboard for visualizing FinRobot agent activities,    ║
║  real-time market data, and trading signals.                                  ║
║                                                                               ║
║  Controls:                                                                    ║
║    q       - Quit                                                             ║
║    SPACE   - Pause/Resume stream                                              ║
║    r       - Refresh display                                                  ║
╚═══════════════════════════════════════════════════════════════════════════════╝
        """
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode with simulated data"
    )

    parser.add_argument(
        "--ticker",
        type=str,
        default="NVDA",
        help="Primary ticker to display (default: NVDA)"
    )

    args = parser.parse_args()

    # Print banner
    print(f"\033[92m")  # Green text
    print("  ╔═══════════════════════════════════════════════════════════╗")
    print("  ║  FINROBOT TERMINAL v1.0                                   ║")
    print("  ║  Initializing neural interface...                         ║")
    print("  ╚═══════════════════════════════════════════════════════════╝")
    print(f"\033[0m")  # Reset

    # Launch app
    app = FinRobotTerminal(demo_mode=args.demo)
    app.run()


if __name__ == "__main__":
    main()
