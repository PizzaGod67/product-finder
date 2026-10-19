"""A tiny terminal table renderer.

Stands in for the `rich` or `tabulate` libraries so the project needs no
installs. Columns are auto-sized, long text is truncated with an ellipsis, and
colour is used only when the terminal actually supports it.
"""

from __future__ import annotations

import os
import re
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"


def colour_enabled() -> bool:
    """Respect NO_COLOR and pipes; Windows terminals need VT enabled."""
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:  # Turn on ANSI escape handling in the Windows console.
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            return False
    return True


class Painter:
    """Applies colour, or quietly does nothing when colour is unavailable."""

    def __init__(self, enabled: bool | None = None):
        self.enabled = colour_enabled() if enabled is None else enabled

    def _wrap(self, text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap(text, BOLD)

    def dim(self, text: str) -> str:
        return self._wrap(text, DIM)

    def good(self, text: str) -> str:
        return self._wrap(text, GREEN)

    def warn(self, text: str) -> str:
        return self._wrap(text, YELLOW)

    def bad(self, text: str) -> str:
        return self._wrap(text, RED)

    def accent(self, text: str) -> str:
        return self._wrap(text, CYAN)


_ANSI = re.compile(r"\033\[[0-9;]*m")


def visible_len(text: str) -> int:
    """Length as the user sees it: colour escape codes take up no space.

    Without this, any coloured cell would be padded as if the invisible
    escape codes were characters, and the columns would not line up.
    """
    return len(_ANSI.sub("", text))


def truncate(text: str, width: int) -> str:
    text = " ".join(str(text).split())  # collapse newlines/tabs
    if visible_len(text) <= width:
        return text
    if _ANSI.search(text):
        return text  # never cut a coloured cell mid-escape-sequence
    # "..." rather than a single ellipsis character, which some Windows
    # consoles cannot encode.
    return text[: max(0, width - 3)] + "..."


def render_table(
    headers: list[str],
    rows: list[list[str]],
    *,
    max_widths: list[int] | None = None,
    align: str = "",
) -> str:
    """Render an ASCII table.

    `align` is a string of 'l' / 'r' characters, one per column.
    `max_widths` caps individual columns; 0 means no cap.
    """
    if not rows:
        return "(no rows)"

    column_count = len(headers)
    caps = (max_widths or []) + [0] * column_count
    aligns = (align or "l" * column_count).ljust(column_count, "l")

    cells = [
        [
            truncate(row[i] if i < len(row) else "", caps[i] or 10**6)
            for i in range(column_count)
        ]
        for row in rows
    ]
    header_cells = [truncate(h, caps[i] or 10**6) for i, h in enumerate(headers)]

    widths = [
        max(
            visible_len(header_cells[i]),
            max((visible_len(r[i]) for r in cells), default=0),
        )
        for i in range(column_count)
    ]

    def line(values: list[str]) -> str:
        parts = []
        for i, value in enumerate(values):
            # Pad by hand, because str.ljust would count the escape codes.
            padding = " " * max(0, widths[i] - visible_len(value))
            parts.append(padding + value if aligns[i] == "r" else value + padding)
        return "  ".join(parts).rstrip()

    # Underline only the columns that actually have a heading.
    separator = "  ".join(
        ("-" * widths[i]) if header_cells[i] else (" " * widths[i])
        for i in range(column_count)
    ).rstrip()
    return "\n".join([line(header_cells), separator, *(line(r) for r in cells)])


def money(value: float, currency: str = "$") -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{currency}{abs(value):,.2f}"


def percent(value: float, places: int = 0) -> str:
    """0.065 -> '7%', or '6.5%' with places=1. Trailing zeros are trimmed."""
    text = f"{value * 100:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"
