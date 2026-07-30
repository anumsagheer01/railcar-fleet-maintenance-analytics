"""
Shared chart styling
====================

One place for colors and fonts so every chart in the project looks like it came
from the same team. Imported by steps 4, 5 and 6.
"""

import matplotlib
matplotlib.use("Agg")          # no display needed, we only write PNG files
import matplotlib.pyplot as plt

# Muted industrial palette. Dark blue for actuals, rust for forecasts and
# anything that needs attention, gray for context.
INK = "#1f2a37"
BLUE = "#2c5f8a"
LIGHT_BLUE = "#8fb3cc"
RUST = "#b4532a"
AMBER = "#c98a20"
GREEN = "#3f7d5c"
GRAY = "#8a939e"
GRID = "#e3e7ec"

SERIES = [BLUE, RUST, GREEN, AMBER, LIGHT_BLUE, GRAY]


def apply_style():
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK,
        "axes.titlecolor": INK,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlepad": 12,
        "axes.labelsize": 10,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.9,
        "xtick.color": GRAY,
        "ytick.color": GRAY,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "font.family": "DejaVu Sans",
        "figure.dpi": 130,
        "savefig.bbox": "tight",
    })


def strip_frame(ax, keep_left=True):
    """Remove the box around the plot. Less ink, easier to read."""
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    if not keep_left:
        ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.spines["left"].set_color(GRID)


def save(fig, path):
    fig.savefig(path)
    plt.close(fig)
    print(f"     chart -> {path.split('/')[-1]}")
