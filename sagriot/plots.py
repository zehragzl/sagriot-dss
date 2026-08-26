import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import VWC_FIELD_CAPACITY
from .features import compute_vpd

FIGURES = "figures"
LOG = "data/real_log.csv"
BENCH_REAL = "results/benchmark_real_log.csv"
BENCH_REF = "results/benchmark_mugrow_agrifusion.csv"

GREEN = "#2F5233"
AMBER = "#C8912B"
RED = "#8B0000"
GREY = "#555555"

WATERINGS = ["2026-08-19 15:05", "2026-08-21 16:56"]

MODEL_ORDER = ["persistence", "seasonal_naive(288)", "damped_trend",
               "driven_drying(vpd)", "driven_drying(vpd+par)",
               "chronos:chronos-bolt-tiny", "chronos:chronos-bolt-small"]
SHORT = {
    "persistence": "persistence",
    "seasonal_naive(288)": "seasonal naive",
    "damped_trend": "damped trend",
    "driven_drying(vpd)": "driven drying\n(VPD)",
    "driven_drying(vpd+par)": "driven drying\n(VPD+PAR)",
    "chronos:chronos-bolt-tiny": "Chronos tiny",
    "chronos:chronos-bolt-small": "Chronos small",
}


def _log():
    frame = pd.read_csv(LOG, parse_dates=["timestamp"]).set_index("timestamp")
    frame["soil_fc_calc"] = frame["soil_vwc"] / VWC_FIELD_CAPACITY * 100
    frame["vpd"] = [compute_vpd(t, h) for t, h in zip(frame["air_temp"], frame["air_humidity"])]
    return frame


def _save(fig, name):
    os.makedirs(FIGURES, exist_ok=True)
    path = os.path.join(FIGURES, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"written {path}")


# ---------------------------------------------------------------- figure 1
def fig_drydown(frame):
    fig, ax = plt.subplots(figsize=(11, 4.2), constrained_layout=True)
    series = frame["soil_fc_calc"].resample("10min").mean()
    ax.plot(series.index, series.values, color=GREEN, linewidth=1.4)

    ax.axhline(70, color=AMBER, linestyle="--", linewidth=1.1)
    ax.axhline(60, color=RED, linestyle="--", linewidth=1.1)
    ax.text(series.index[3], 70.8, "warning threshold (70 %FC)", color=AMBER, fontsize=8)
    ax.text(series.index[3], 60.8, "critical threshold (60 %FC)", color=RED, fontsize=8)

    for stamp in WATERINGS:
        moment = pd.Timestamp(stamp, tz=series.index.tz)
        ax.axvline(moment, color=GREY, linestyle=":", linewidth=1.1)
        ax.text(moment, series.max() * 0.99, " irrigation", rotation=90,
                va="top", fontsize=8, color=GREY)

    values = series.values
    crossings = series.index[1:][(values[:-1] >= 70) & (values[1:] < 70)]
    for moment in crossings:
        ax.plot(moment, 70, marker="v", color=AMBER, markersize=8, zorder=5)
        ax.annotate(moment.strftime("%d %b %H:%M"), (moment, 70),
                    textcoords="offset points", xytext=(6, -16),
                    fontsize=8, color=AMBER)

    ax.set_ylabel("soil moisture (% of field capacity)")
    ax.set_title("Two drydown cycles on the single-pot testbed", loc="left",
                 fontsize=11, fontweight="bold")
    ax.grid(alpha=0.25)
    fig.text(0.005, -0.03,
             "Thresholds are the tomato configuration applied to a surrogate plant "
             "(chrysanthemum) as fixed event markers — not horticultural advice for this species.",
             fontsize=8, color=GREY)
    _save(fig, "fig1_drydown_cycles.png")


# ---------------------------------------------------------------- figure 2
def fig_rate_vs_vpd(frame):
    segments = [("2026-08-19 19:30", "2026-08-21 16:50"),
                ("2026-08-21 21:00", frame.index[-1].strftime("%Y-%m-%d %H:%M"))]
    parts = []
    for start, end in segments:
        window = frame.loc[start:end].resample("2h").mean(numeric_only=True)
        window["rate"] = -window["soil_vwc"].diff() / 2
        parts.append(window.dropna(subset=["rate"]))
    data = pd.concat(parts)
    data = data[data["rate"] > -0.1]

    slope, intercept = np.polyfit(data["vpd"], data["rate"], 1)
    predicted = slope * data["vpd"] + intercept
    r2 = np.corrcoef(predicted, data["rate"])[0, 1] ** 2

    fig, ax = plt.subplots(figsize=(6.2, 4.6), constrained_layout=True)
    points = ax.scatter(data["vpd"], data["rate"], c=data["air_temp"],
                        cmap="YlOrRd", s=34, edgecolor="white", linewidth=0.5)
    grid = np.linspace(data["vpd"].min(), data["vpd"].max(), 50)
    ax.plot(grid, slope * grid + intercept, color=GREEN, linewidth=1.6)
    ax.text(0.04, 0.94,
            f"rate = {slope:.3f}·VPD − {abs(intercept):.3f}\nR² = {r2:.3f}   n = {len(data)}",
            transform=ax.transAxes, va="top", fontsize=9,
            bbox=dict(facecolor="white", edgecolor="#DDDDDD"))

    fig.colorbar(points, ax=ax, label="air temperature (°C)")
    ax.set_xlabel("vapour pressure deficit (kPa)")
    ax.set_ylabel("drying rate (%VWC h⁻¹)")
    ax.set_title("Drying rate tracks evaporative demand", loc="left",
                 fontsize=11, fontweight="bold")
    ax.grid(alpha=0.25)
    _save(fig, "fig2_rate_vs_vpd.png")


# ---------------------------------------------------------------- figure 3
def fig_skill_matrix():
    real = pd.read_csv(BENCH_REAL)
    ref = pd.read_csv(BENCH_REF)
    ref = ref[ref["dataset"] == "mugrow"]
    real = real.replace({"channel": {"soil_vwc": "soil moisture"}})
    ref = ref.replace({"channel": {"soil_fc": "soil moisture"}})

    channels = ["air_temp", "air_humidity", "par", "co2", "soil moisture", "soil_temp", "ec"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.4), constrained_layout=True)

    for ax, (frame, title) in zip(axes, [(ref, "Commercial greenhouse (Wageningen)"),
                                         (real, "Office testbed")]):
        table = frame.pivot_table(index="model", columns="channel", values="skill")
        table = table.reindex(index=[m for m in MODEL_ORDER if m in table.index],
                              columns=[c for c in channels if c in table.columns])
        image = ax.imshow(table.values, cmap="RdYlGn", vmin=-0.5, vmax=0.5, aspect="auto")
        ax.set_xticks(range(table.shape[1]))
        ax.set_xticklabels(table.columns, rotation=35, ha="right", fontsize=9)
        ax.set_yticks(range(table.shape[0]))
        ax.set_yticklabels([SHORT.get(m, m).replace("\n", " ") for m in table.index], fontsize=9)
        for i in range(table.shape[0]):
            for j in range(table.shape[1]):
                value = table.values[i, j]
                if not np.isnan(value):
                    ax.text(j, i, f"{value:+.2f}", ha="center", va="center", fontsize=8)
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold")

    fig.colorbar(image, ax=axes, label="skill vs persistence", shrink=0.8)
    fig.suptitle("The best method depends on the environment, not the channel alone",
                 fontsize=12, x=0.01, ha="left")
    _save(fig, "fig3_skill_matrix.png")


# ---------------------------------------------------------------- figure 4
def fig_decision_metrics():
    real = pd.read_csv(BENCH_REAL)
    soil = real[real["channel"] == "soil_vwc"].set_index("model")
    soil = soil.reindex([m for m in MODEL_ORDER if m in soil.index])

    labels = [SHORT.get(m, m) for m in soil.index]
    x = np.arange(len(soil))
    width = 0.36

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9.5, 6.4), sharex=True,
                                      gridspec_kw={"height_ratios": [2, 1]},
                                      constrained_layout=True)

    top.bar(x - width / 2, soil["recall"].fillna(0), width, label="recall", color=GREEN)
    top.bar(x + width / 2, soil["precision"].fillna(0), width, label="precision", color=AMBER)
    top.set_ylim(0, 1.15)
    top.set_ylabel("fraction")
    top.legend(frameon=False, ncol=2)
    top.grid(axis="y", alpha=0.25)
    top.set_title("Soil-moisture level crossings — detection quality (6 events)",
                  loc="left", fontsize=11, fontweight="bold")
    fig.text(0.005, -0.07,
             "Evaluation level is the 15th percentile of the recorded series, chosen to give "
             "enough events for scoring;\nit is not the 70 %FC operational threshold of Figure 1.",
             fontsize=8, color=GREY)
    for index, model in enumerate(soil.index):
        if pd.isna(soil.loc[model, "recall"]) or soil.loc[model, "recall"] == 0:
            top.text(index, 0.04, "never warns", ha="center", fontsize=8, color=RED)

    bottom.bar(x, soil["cross_err_min"], 0.5, color=GREY)
    bottom.set_ylabel("timing error\n(minutes)")
    bottom.set_xticks(x)
    bottom.set_xticklabels(labels, fontsize=9)
    bottom.grid(axis="y", alpha=0.25)

    _save(fig, "fig4_decision_metrics.png")


# ---------------------------------------------------------------- figure 5
def fig_cost_benefit():
    real = pd.read_csv(BENCH_REAL)
    soil = real[real["channel"] == "soil_vwc"].set_index("model")

    # measured on the Raspberry Pi 5, mean of 20 inferences
    pi_latency = {
        "persistence": 0.004,
        "seasonal_naive(288)": 0.010,
        "damped_trend": 11.56,
        "driven_drying(vpd)": 0.070,
        "driven_drying(vpd+par)": 0.070,
        "chronos:chronos-bolt-tiny": 34.53,
        "chronos:chronos-bolt-small": 122.47,
    }
    pi_memory = {
        "persistence": 0.05, "seasonal_naive(288)": 0.05, "damped_trend": 0.05,
        "driven_drying(vpd)": 0.1, "driven_drying(vpd+par)": 0.1,
        "chronos:chronos-bolt-tiny": 358.6, "chronos:chronos-bolt-small": 533.3,
    }

    offsets = {
        "persistence": (10, -4),
        "damped_trend": (-14, 12),
        "driven_drying(vpd)": (10, 8),
        "driven_drying(vpd+par)": (10, -14),
        "chronos:chronos-bolt-tiny": (-20, 16),
        "chronos:chronos-bolt-small": (-70, 12),
    }

    fig, ax = plt.subplots(figsize=(8.2, 5.2), constrained_layout=True)
    for model in soil.index:
        if model not in pi_latency or model == "seasonal_naive(288)":
            continue
        size = 40 + 260 * np.sqrt(pi_memory[model] / 533.3)
        colour = RED if model.startswith("chronos") else GREEN
        ax.scatter(pi_latency[model], soil.loc[model, "skill"], s=size,
                   color=colour, alpha=0.75, edgecolor="white", linewidth=1.2, zorder=3)
        ax.annotate(SHORT.get(model, model).replace("\n", " "),
                    (pi_latency[model], soil.loc[model, "skill"]),
                    textcoords="offset points", xytext=offsets.get(model, (9, 6)),
                    fontsize=9)

    ax.set_xscale("log")
    ax.set_ylim(-0.06, 0.34)
    ax.axhline(0, color=GREY, linewidth=0.9, linestyle="--")
    ax.text(0.015, -0.045, "seasonal naive omitted (skill −10.1)",
            fontsize=8, color=GREY)
    ax.set_xlabel("inference latency on Raspberry Pi 5 (ms, log scale)")
    ax.set_ylabel("forecast skill vs persistence")
    ax.set_title("Soil moisture: accuracy against computational cost",
                 loc="left", fontsize=11, fontweight="bold")
    ax.text(0.99, 0.03, "marker area ∝ resident memory", transform=ax.transAxes,
            ha="right", fontsize=8, color=GREY)
    ax.grid(alpha=0.25, which="both")
    _save(fig, "fig5_cost_benefit.png")


def main():
    frame = _log()
    fig_drydown(frame)
    fig_rate_vs_vpd(frame)
    fig_skill_matrix()
    fig_decision_metrics()
    fig_cost_benefit()


if __name__ == "__main__":
    main()
