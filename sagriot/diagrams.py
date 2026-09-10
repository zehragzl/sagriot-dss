"""The two diagrams the report needs: how it is wired, and how it works.

Drawn rather than photographed, because a photograph of this node shows a
handful of cables and tells you nothing about which wire is which.

    python -m sagriot.diagrams

Writes figures/fig0a_hardware.png and figures/fig0b_flow.png.
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

FIGURES = "figures"

# Header pin the Stemma QT rail is powered from. Pin 1 is 3V3, pin 2 is 5V;
# these boards accept either. SDA is pin 3, SCL pin 5, GND pin 6 in both cases.
POWER_PIN = 1

# Order along the Stemma QT chain after the SHT31. Electrically irrelevant -
# it is one bus - but the drawing should match the cable.
CHAIN = [("SHT31-D", "0x44", "air temp\nhumidity"),
         ("SCD41", "0x62", "CO₂"),
         ("DPS310", "0x77", "pressure"),
         ("TSL2591", "0x29", "light")]

GREEN = "#2F5233"
AMBER = "#C8912B"
RED = "#8B0000"
BLUE = "#2C4A6E"
GREY = "#555555"
FAINT = "#EDEDED"


def _save(fig, name):
    os.makedirs(FIGURES, exist_ok=True)
    path = os.path.join(FIGURES, name)
    fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"written {path}")


def box(ax, x, y, width, height, title, subtitle=None, colour=BLUE,
        fill=FAINT, size=8):
    ax.add_patch(FancyBboxPatch((x, y), width, height,
                                boxstyle="round,pad=0.35,rounding_size=0.8",
                                linewidth=1.2, edgecolor=colour, facecolor=fill))
    centre = x + width / 2
    if subtitle:
        ax.text(centre, y + height * 0.63, title, ha="center", va="center",
                fontsize=size, fontweight="bold", color=colour)
        ax.text(centre, y + height * 0.27, subtitle, ha="center", va="center",
                fontsize=size - 1.2, color=GREY, linespacing=1.15)
    else:
        ax.text(centre, y + height / 2, title, ha="center", va="center",
                fontsize=size, fontweight="bold", color=colour)


def wire(ax, points, colour=GREY, width=1.1, style="-", label=None,
         label_at=None, label_size=6.8, label_colour=None):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    ax.plot(xs, ys, color=colour, linewidth=width, linestyle=style,
            solid_capstyle="round", zorder=1)
    if label:
        x, y = label_at or points[0]
        ax.text(x, y, label, fontsize=label_size,
                color=label_colour or colour, ha="left", va="bottom")


# --------------------------------------------------------------- hardware
def hardware():
    fig, ax = plt.subplots(figsize=(12.5, 6.4))
    ax.set_xlim(0, 118)
    ax.set_ylim(-14, 60)
    ax.axis("off")

    # --- the four I2C rails, Pi header -> breadboard
    rails = [(f"pin {POWER_PIN}", "3V3" if POWER_PIN == 1 else "5V", 44, AMBER),
             ("pin 3", "SDA", 39, BLUE),
             ("pin 5", "SCL", 34, BLUE),
             ("pin 6", "GND", 29, "#333333")]

    box(ax, 2, 24, 20, 24, "Raspberry Pi 5", "40-pin header\n+ USB", colour=GREEN,
        fill="#EAF0EA", size=9)

    for pin, signal, y, colour in rails:
        wire(ax, [(22, y), (33, y)], colour=colour, width=1.6)
        ax.text(23.5, y + 0.9, pin, fontsize=6.5, color=GREY)
        ax.text(31.5, y + 0.9, signal, fontsize=6.5, color=colour,
                ha="right", fontweight="bold")

    # --- breadboard
    ax.add_patch(FancyBboxPatch((33, 25), 6, 24,
                                boxstyle="round,pad=0.3,rounding_size=0.6",
                                linewidth=1.2, edgecolor=BLUE, facecolor="#DCE8F5"))
    ax.text(36, 37, "breadboard", rotation=90, ha="center", va="center",
            fontsize=8, color=BLUE, fontweight="bold")
    ax.text(36, 21, "four rails,\ntwo branches", ha="center",
            va="top", fontsize=6.8, color=GREY, linespacing=1.2)

    # --- branch 1: the Stemma QT chain
    left = 45
    width, gap, y = 16, 2.5, 42
    for number, (name, address, measures) in enumerate(CHAIN):
        x = left + number * (width + gap)
        box(ax, x, y, width, 11, name, f"{address}\n{measures}", colour=BLUE, size=8)
        if number == 0:
            wire(ax, [(39, 39), (42, 39), (42, y + 5.5), (x, y + 5.5)],
                 colour=BLUE, width=2.8)
            ax.text(40.2, 39.8, "4 wires,\nmale → QT", fontsize=6.5,
                    color=GREY, ha="left", va="bottom", linespacing=1.2)
        else:
            wire(ax, [(x - gap, y + 5.5), (x, y + 5.5)], colour=BLUE, width=1.6)
            ax.text(x - gap / 2, y + 6.3, "QT", fontsize=6, color=GREY, ha="center")

    ax.text(left + 2 * (width + gap), 57, "one I²C bus — every device at its own address",
            ha="center", fontsize=7.5, color=BLUE, style="italic")

    # --- branch 2: the clock
    box(ax, 45, 25, 16, 10, "DS3231", "0x68\nreal-time clock", colour=BLUE, size=8)
    wire(ax, [(39, 34), (42, 34), (42, 30), (45, 30)], colour=BLUE, width=2.8)
    ax.text(40.2, 32.6, "4 wires", fontsize=6.5, color=GREY, ha="left", va="top")
    ax.text(62.5, 30, "the node timestamps its own readings,\n"
                      "so it does not depend on network time",
            fontsize=6.8, color=GREY, va="center", linespacing=1.3)

    # --- the RS485 side
    box(ax, 86, -9, 26, 14, "RS485 soil probe", "moisture · root temp\n· bulk EC",
        colour=GREEN, fill="#EAF0EA", size=8.5)
    box(ax, 50, -1, 22, 9, "USB → RS485", "Modbus RTU, 9600 Bd", colour=GREEN,
        fill="#EAF0EA", size=8)
    box(ax, 50, -13, 22, 8, "12 V supply", None, colour="#333333", fill=FAINT, size=8)

    # data pair
    wire(ax, [(86, 3.5), (78, 3.5), (78, 5), (72, 5)], colour=GREEN, width=1.6)
    wire(ax, [(86, 1.5), (80, 1.5), (80, 2.5), (72, 2.5)], colour=GREEN, width=1.6)
    ax.text(79, 6.5, "A / B", fontsize=6.8, color=GREEN, ha="center",
            fontweight="bold")

    # power pair
    wire(ax, [(86, -5), (78, -5), (78, -8), (72, -8)], colour="#333333", width=1.6)
    wire(ax, [(86, -7), (76, -7), (76, -10), (72, -10)], colour="#333333", width=1.6)
    ax.text(79, -4.2, "12 V, GND", fontsize=6.8, color="#333333", ha="center")

    # converter into the Pi
    wire(ax, [(50, 3.5), (14, 3.5), (14, 24)], colour=GREEN, width=1.6)
    ax.text(15, 4.6, "USB  → /dev/ttyUSB0", fontsize=6.8, color=GREEN)

    # the fix
    wire(ax, [(61, -5), (61, -1)], colour=RED, width=2.4)
    ax.plot(61, -3, marker="o", color=RED, markersize=5, zorder=4)
    ax.annotate("common ground\nadded here",
                xy=(61, -3), xytext=(30, -11.5), fontsize=7.5, color=RED,
                fontweight="bold", ha="center", linespacing=1.25,
                arrowprops=dict(arrowstyle="->", color=RED, linewidth=1.2))

    ax.text(118, -13.5,
            "Without this wire the probe was powered from one supply and signalled to "
            "another, leaving the common-mode voltage\nunreferenced: roughly half of all "
            "frames were corrupted, at arbitrary positions rather than at frame "
            "boundaries.\nRS485 is differential but not isolated, and still needs a shared "
            "reference. With it, twenty consecutive reads and no errors.",
            fontsize=7, color=GREY, ha="right", va="top", linespacing=1.4)

    ax.set_title("How the node is wired", loc="left", fontsize=12,
                 fontweight="bold", color="#222222", pad=14)
    _save(fig, "fig0a_hardware.png")


# ------------------------------------------------------------------- flow
def flow():
    fig, ax = plt.subplots(figsize=(12.5, 5.6))
    ax.set_xlim(0, 118)
    ax.set_ylim(0, 58)
    ax.axis("off")

    def arrow(x1, y1, x2, y2, colour=GREY, text=None, dx=0, dy=1.2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=colour, linewidth=1.4))
        if text:
            ax.text((x1 + x2) / 2 + dx, (y1 + y2) / 2 + dy, text, fontsize=6.8,
                    color=GREY, ha="center", linespacing=1.2)

    # --- the measurement path
    top = 34
    box(ax, 1, top, 19, 11, "sensors", "5 × I²C + probe\nevery 30 s",
        colour=GREEN, fill="#EAF0EA")
    box(ax, 25, top, 19, 11, "raw log", "measurements only\nnothing derived",
        colour=BLUE)
    box(ax, 49, top, 19, 11, "features", "VPD · daily light\n· disease hours", colour=BLUE)
    box(ax, 73, top, 19, 11, "seven rules", "thresholds from\nthe crop table", colour=BLUE)
    box(ax, 97, top, 20, 11, "advice now", "what is already\ntrue", colour=AMBER,
        fill="#FBF3E3")

    for x1, x2 in ((20, 25), (44, 49), (68, 73), (92, 97)):
        arrow(x1, top + 5.5, x2, top + 5.5)

    # --- the forecast path
    low = 8
    box(ax, 25, low, 19, 11, "advise", "last 24 h\nread from the tail", colour=BLUE)
    box(ax, 49, low, 19, 11, "forecast", "+3 h per channel\nwith a band", colour=BLUE)
    box(ax, 73, low, 19, 11, "the same rules", "run on predicted\nrows", colour=BLUE)
    box(ax, 97, low, 20, 11, "early warning", "what is about to\nbecome true",
        colour=AMBER, fill="#FBF3E3")

    for x1, x2 in ((44, 49), (68, 73), (92, 97)):
        arrow(x1, low + 5.5, x2, low + 5.5)
    ax.annotate("", xy=(34.5, low + 11), xytext=(34.5, top),
                arrowprops=dict(arrowstyle="-|>", color=GREY, linewidth=1.4))
    ax.text(36, (top + low + 11) / 2, "every 10 min", fontsize=6.8, color=GREY)

    ax.text(107, top - 3.5, "↓", fontsize=11, color=GREY, ha="center")
    ax.text(107, low + 12.5, "a rule already firing is excluded:\nthe layer reports what "
                             "changes,\nnot what is",
            fontsize=6.8, color=GREY, ha="center", va="bottom", linespacing=1.3)

    ax.text(1, 56,
            "The forecast changes no rule. It moves the moment at which the rules are "
            "evaluated, and nothing else — so a wrong forecast\nmakes the advice early or "
            "late, never different.",
            fontsize=8, color="#222222", va="top", linespacing=1.45)

    ax.text(1, low - 2.5,
            "Nothing is actuated. Both paths end in a recommendation a person acts on.",
            fontsize=7.2, color=GREY, va="top", style="italic")

    ax.set_title("How the system works", loc="left", fontsize=12,
                 fontweight="bold", color="#222222", pad=10)
    _save(fig, "fig0b_flow.png")


if __name__ == "__main__":
    hardware()
    flow()
