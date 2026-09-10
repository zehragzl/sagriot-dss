"""Report figures, generated from the frozen 9 September snapshot.

The log and the benchmark file are both arguments rather than constants,
because a figure that silently regenerates itself from a longer record is a
figure whose caption has quietly stopped being true.

    python -m sagriot.plots
    python -m sagriot.plots data/real_log.csv results/benchmark_real_log.csv
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import VWC_FIELD_CAPACITY
from .features import compute_vpd

FIGURES = "figures"
LOG = "data/snapshot_0909.csv"
BENCH = "results/benchmark_snapshot_0909_mugrow_agrifusion.csv"

TESTBED = "snapshot_0909"
GREENHOUSE = "mugrow"

GREEN = "#2F5233"
AMBER = "#C8912B"
RED = "#8B0000"
BLUE = "#2C4A6E"
GREY = "#555555"

# Every watering in the record. The pairs are (moment, what it reached).
WATERINGS = ["2026-08-19 15:05", "2026-08-21 16:56", "2026-08-28 13:14",
             "2026-09-02 13:55", "2026-09-07 12:56"]

# Free-drying stretches: from a few hours after each watering, once drainage
# has finished, to just before the next one. Drainage is not drying and would
# put a steep artificial slope into Figure 2.
DRYING = [("2026-08-19 19:30", "2026-08-21 16:50"),
          ("2026-08-21 21:00", "2026-08-28 13:10"),
          ("2026-08-28 17:30", "2026-09-02 13:50"),
          ("2026-09-02 18:00", "2026-09-07 12:50"),
          ("2026-09-07 17:00", None)]

MODEL_ORDER = ["persistence", "seasonal_naive(288)",
               "driven_drying(vpd)", "driven_drying(vpd+level)",
               "driven_drying(vpd+par)", "ttm",
               "chronos:chronos-bolt-tiny", "chronos:chronos-bolt-small",
               "ensemble(driven_drying(vpd)+chronos:chronos-bolt-tiny)"]
SHORT = {
    "persistence": "persistence",
    "seasonal_naive(288)": "seasonal naive",
    "driven_drying(vpd)": "driven drying\n(VPD)",
    "driven_drying(vpd+level)": "driven drying\n(VPD+level)",
    "driven_drying(vpd+par)": "driven drying\n(VPD+PAR)",
    "ttm": "TTM",
    "chronos:chronos-bolt-tiny": "Chronos tiny",
    "chronos:chronos-bolt-small": "Chronos small",
    "ensemble(driven_drying(vpd)+chronos:chronos-bolt-tiny)": "ensemble",
}

CHANNEL_LABEL = {
    "air_temp": "air temp", "air_humidity": "air humidity",
    "par": "light (PAR)", "co2": "CO₂",
    "soil moisture": "soil moisture", "soil_temp": "soil temp", "ec": "EC",
}

# Resident memory of the process, measured on the Raspberry Pi 5 with one
# method loaded per process. The analytic models load no framework at all;
# 0.1 MB stands for "below what the measurement can resolve".
PI_MEMORY = {
    "persistence": 0.1, "seasonal_naive(288)": 0.1,
    "driven_drying(vpd)": 0.1, "driven_drying(vpd+level)": 0.1,
    "driven_drying(vpd+par)": 0.1,
    "ttm": 718.0,
    "chronos:chronos-bolt-tiny": 728.0,
    "chronos:chronos-bolt-small": 884.0,
}


def _log(path):
    frame = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp")
    frame["soil_fc_calc"] = frame["soil_vwc"] / VWC_FIELD_CAPACITY * 100
    frame["vpd"] = [compute_vpd(t, h)
                    for t, h in zip(frame["air_temp"], frame["air_humidity"])]
    return frame


def _bench(path):
    frame = pd.read_csv(path)
    return frame.replace({"channel": {"soil_vwc": "soil moisture",
                                      "soil_fc": "soil moisture"}})


def _soil(bench, dataset):
    part = bench[(bench["dataset"] == dataset) & (bench["channel"] == "soil moisture")]
    part = part.set_index("model")
    return part.reindex([m for m in MODEL_ORDER if m in part.index])


def _save(fig, name):
    os.makedirs(FIGURES, exist_ok=True)
    path = os.path.join(FIGURES, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"written {path}")


# ---------------------------------------------------------------- figure 1
def fig_drydown(frame):
    fig, ax = plt.subplots(figsize=(12, 4.2), constrained_layout=True)
    series = frame["soil_fc_calc"].resample("10min").mean()
    ax.plot(series.index, series.values, color=GREEN, linewidth=1.2)

    ax.axhline(70, color=AMBER, linestyle="--", linewidth=1.1)
    ax.axhline(60, color=RED, linestyle="--", linewidth=1.1)
    ax.text(series.index[3], 72.0, "warning threshold (70 %FC)", color=AMBER, fontsize=8)
    ax.text(series.index[3], 55.5, "critical threshold (60 %FC)", color=RED, fontsize=8)

    for number, stamp in enumerate(WATERINGS, start=1):
        moment = pd.Timestamp(stamp, tz=series.index.tz)
        ax.axvline(moment, color=GREY, linestyle=":", linewidth=1.1)
        ax.text(moment, series.max() * 0.99, f" {number}", rotation=0,
                va="top", fontsize=8, color=GREY)

    values = series.values
    crossings = series.index[1:][(values[:-1] >= 70) & (values[1:] < 70)]
    for moment in crossings:
        ax.plot(moment, 70, marker="v", color=AMBER, markersize=7, zorder=5)

    ax.set_ylabel("soil moisture (% of field capacity)")
    ax.set_title("Twenty-one days on the single-pot testbed, five irrigations",
                 loc="left", fontsize=11, fontweight="bold")
    ax.grid(alpha=0.25)
    fig.text(0.005, -0.09,
             "Thresholds are the tomato configuration applied to a surrogate plant "
             "(chrysanthemum) as fixed event markers — not horticultural advice for this "
             "species.\nMarkers show every downward crossing of 70 %FC; several belong to "
             "the same physical event.",
             fontsize=8, color=GREY)
    _save(fig, "fig1_drydown_cycles.png")


# ---------------------------------------------------------------- figure 2
def fig_rate_vs_vpd(frame):
    parts = []
    for start, end in DRYING:
        end = end or frame.index[-1].strftime("%Y-%m-%d %H:%M")
        window = frame.loc[start:end].resample("2h").mean(numeric_only=True)
        window["rate"] = -window["soil_vwc"].diff() / 2
        parts.append(window.dropna(subset=["rate"]))
    data = pd.concat(parts)
    data = data[data["rate"] > -0.1]

    slope, intercept = np.polyfit(data["vpd"], data["rate"], 1)
    predicted = slope * data["vpd"] + intercept
    r2 = np.corrcoef(predicted, data["rate"])[0, 1] ** 2

    fig, ax = plt.subplots(figsize=(6.4, 4.6), constrained_layout=True)
    points = ax.scatter(data["vpd"], data["rate"], c=data["air_temp"],
                        cmap="YlOrRd", s=30, edgecolor="white", linewidth=0.4)
    grid = np.linspace(data["vpd"].min(), data["vpd"].max(), 50)
    ax.plot(grid, slope * grid + intercept, color=GREEN, linewidth=1.6)
    sign = "−" if intercept < 0 else "+"
    ax.text(0.04, 0.94,
            f"rate = {slope:.3f}·VPD {sign} {abs(intercept):.3f}\n"
            f"R² = {r2:.3f}   n = {len(data)}",
            transform=ax.transAxes, va="top", fontsize=9,
            bbox=dict(facecolor="white", edgecolor="#DDDDDD"))

    fig.colorbar(points, ax=ax, label="air temperature (°C)")
    ax.set_xlabel("vapour pressure deficit (kPa)")
    ax.set_ylabel("drying rate (%VWC h⁻¹)")
    ax.set_title("Drying rate tracks evaporative demand", loc="left",
                 fontsize=11, fontweight="bold")
    ax.grid(alpha=0.25)
    fig.text(0.005, -0.04,
             "Five free-drying stretches, drainage hours after each watering excluded. "
             "This is the relation the two-coefficient model fits.",
             fontsize=8, color=GREY)
    _save(fig, "fig2_rate_vs_vpd.png")


# ---------------------------------------------------------------- figure 3
def fig_skill_matrix(bench):
    channels = ["air_temp", "air_humidity", "par", "co2",
                "soil moisture", "soil_temp", "ec"]
    panels = [(GREENHOUSE, "Commercial greenhouse (Wageningen)"),
              (TESTBED, "Office testbed")]

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), constrained_layout=True)
    for ax, (dataset, title) in zip(axes, panels):
        frame = bench[bench["dataset"] == dataset]
        table = frame.pivot_table(index="model", columns="channel", values="skill")
        table = table.reindex(index=[m for m in MODEL_ORDER if m in table.index],
                              columns=[c for c in channels if c in table.columns])
        image = ax.imshow(table.values, cmap="RdYlGn", vmin=-0.5, vmax=0.5, aspect="auto")
        ax.set_xticks(range(table.shape[1]))
        ax.set_xticklabels([CHANNEL_LABEL.get(c, c) for c in table.columns],
                           rotation=35, ha="right", fontsize=9)
        ax.set_yticks(range(table.shape[0]))
        ax.set_yticklabels([SHORT.get(m, m).replace("\n", " ") for m in table.index],
                           fontsize=9)
        for i in range(table.shape[0]):
            for j in range(table.shape[1]):
                value = table.values[i, j]
                if not np.isnan(value):
                    ax.text(j, i, f"{value:+.2f}", ha="center", va="center", fontsize=7.5)
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold")

    fig.colorbar(image, ax=axes, label="skill vs persistence", shrink=0.8)
    fig.suptitle("The best method depends on the environment, not the channel alone",
                 fontsize=12, x=0.01, ha="left")
    fig.text(0.005, -0.04,
             "Read the light column: repeating yesterday is the best forecaster of light "
             "in the greenhouse and worse than doing nothing in the office.\n"
             "Values below −0.5 are clipped by the colour scale; seasonal naive reaches "
             "−10.3 on testbed soil moisture.",
             fontsize=8, color=GREY)
    _save(fig, "fig3_skill_matrix.png")


# ---------------------------------------------------------------- figure 4
def fig_decision_metrics(bench):
    soil = _soil(bench, TESTBED)
    events = int(soil["events"].dropna().iloc[0])

    labels = [SHORT.get(m, m) for m in soil.index]
    x = np.arange(len(soil))
    width = 0.36

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(10.5, 6.4), sharex=True,
                                      gridspec_kw={"height_ratios": [2, 1]},
                                      constrained_layout=True)

    top.bar(x - width / 2, soil["recall"].fillna(0), width, label="recall", color=GREEN)
    top.bar(x + width / 2, soil["precision"].fillna(0), width, label="precision", color=AMBER)
    top.set_ylim(0, 1.18)
    top.set_ylabel("fraction")
    top.legend(frameon=False, ncol=2, loc="upper left")
    top.grid(axis="y", alpha=0.25)
    top.set_title(f"Soil-moisture level crossings — detection quality "
                  f"({events} scored windows, 4 physical events)",
                  loc="left", fontsize=11, fontweight="bold")
    for index, model in enumerate(soil.index):
        recall = soil.loc[model, "recall"]
        if pd.isna(recall) or recall == 0:
            top.text(index, 0.04, "never warns", ha="center", fontsize=8, color=RED)

    bottom.bar(x, soil["cross_err_min"], 0.5, color=GREY)
    bottom.set_ylabel("timing error\n(minutes)")
    bottom.set_xticks(x)
    bottom.set_xticklabels(labels, fontsize=8.5)
    bottom.grid(axis="y", alpha=0.25)

    fig.text(0.005, -0.07,
             "Evaluation level is a percentile of the recorded series, frozen so that runs "
             "on records of different length stay comparable;\nit is not the 70 %FC "
             "operational threshold of Figure 1. Bars are absent where a method never "
             "warned and timing is undefined.",
             fontsize=8, color=GREY)
    _save(fig, "fig4_decision_metrics.png")


# ---------------------------------------------------------------- figure 5
def fig_cost_benefit(bench):
    soil = _soil(bench, TESTBED)

    offsets = {
        "persistence": (10, -4),
        "driven_drying(vpd)": (14, -8),
        "driven_drying(vpd+level)": (-34, 14),
        "driven_drying(vpd+par)": (11, -16),
        "ttm": (14, 2),
        "chronos:chronos-bolt-tiny": (-34, 18),
        "chronos:chronos-bolt-small": (-96, -20),
    }

    fig, ax = plt.subplots(figsize=(8.6, 5.2), constrained_layout=True)
    for model in soil.index:
        if model == "seasonal_naive(288)" or model not in PI_MEMORY:
            continue
        memory = PI_MEMORY[model]
        size = 40 + 260 * np.sqrt(memory / 884.0)
        colour = GREEN if memory < 1 else RED
        ax.scatter(soil.loc[model, "ms"], soil.loc[model, "skill"], s=size,
                   color=colour, alpha=0.75, edgecolor="white", linewidth=1.2, zorder=3)
        ax.annotate(SHORT.get(model, model).replace("\n", " "),
                    (soil.loc[model, "ms"], soil.loc[model, "skill"]),
                    textcoords="offset points", xytext=offsets.get(model, (9, 6)),
                    fontsize=9)

    ax.set_xscale("log")
    ax.set_ylim(-0.45, 0.30)
    ax.axhline(0, color=GREY, linewidth=0.9, linestyle="--")
    ax.text(ax.get_xlim()[1] * 0.9, 0.012, "persistence baseline",
            ha="right", fontsize=8, color=GREY)
    ax.set_xlabel("time per forecast on Raspberry Pi 5 (ms, log scale)")
    ax.set_ylabel("forecast skill vs persistence")
    ax.set_title("Soil moisture: accuracy against computational cost",
                 loc="left", fontsize=11, fontweight="bold")
    ax.text(0.99, 0.97, "marker area ∝ resident memory", transform=ax.transAxes,
            ha="right", va="top", fontsize=8, color=GREY)
    ax.grid(alpha=0.25, which="both")
    fig.text(0.005, -0.04,
             "Seasonal naive omitted: at skill −10.3 it would compress everything else "
             "into a line. Green markers hold no framework;\nthe red ones each hold "
             "roughly 0.7–0.9 GB whether they are computing or not. Latency is the mean "
             "over all evaluation windows and includes the on-site fit.",
             fontsize=8, color=GREY)
    _save(fig, "fig5_cost_benefit.png")


def main(log=LOG, bench=BENCH):
    frame = _log(log)
    print(f"log: {len(frame)} rows, {frame.index[0]} -> {frame.index[-1]}")
    table = _bench(bench)
    fig_drydown(frame)
    fig_rate_vs_vpd(frame)
    fig_skill_matrix(table)
    fig_decision_metrics(table)
    fig_cost_benefit(table)


if __name__ == "__main__":
    main(*(sys.argv[1:3] or []))
