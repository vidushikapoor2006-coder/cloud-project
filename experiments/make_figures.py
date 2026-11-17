"""
Regenerate every result figure of the revised paper from experiment outputs.
No number is hard-coded: all values are read from results/.

    python -m experiments.make_figures            -> paper/figures/*.pdf (+ .png)
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
RES = os.path.join(ROOT, "results")
OUT = os.environ.get("FIG_DIR", os.path.join(ROOT, "figures"))

import config  # noqa: E402

# Fixed entity -> colour/marker/linestyle (validated categorical palette;
# markers and dashes give a second, colour-independent encoding).
STYLE = {
    "Static":         ("#52514e", "x", (0, (1, 1))),
    "Utility-Based":  ("#2a78d6", "s", (0, (4, 2))),
    "QoS-Based":      ("#2a78d6", "s", (0, (4, 2))),
    "Resource-Aware": ("#2a78d6", "s", (0, (4, 2))),
    "AMC-Adapted":    ("#eb6834", "v", (0, (6, 2, 1, 2))),
    "Elastic-MC":     ("#1baf7a", "^", (0, (3, 1, 1, 1))),
    "MDP-Migration":  ("#e34948", "s", (0, (1, 1, 3, 1))),
    "Proposed-v1":    ("#e87ba4", "D", (0, (2, 2))),
    "Proposed":       ("#6250d6", "o", "-"),
    "RH-DP":          ("#eda100", "P", (0, (5, 1))),
    "RH-DP-Oracle":   ("#008300", "*", (0, (1, 2))),
}
PLOT_POLICIES = ["Static", "Utility-Based", "AMC-Adapted", "Elastic-MC",
                 "Proposed-v1", "Proposed", "RH-DP"]
ALL_POLICIES = ["Static", "QoS-Based", "Resource-Aware", "Utility-Based",
                "AMC-Adapted", "Elastic-MC", "MDP-Migration", "Proposed-v1", "Proposed",
                "RH-DP", "RH-DP-Oracle"]
DISPLAY = {"AMC-Adapted": "AMC-inspired", "Elastic-MC": "EMC-inspired"}
SHORT = {"Static": "Static", "MDP-Migration": "MDP-Mig.", "QoS-Based": "QoS", "Resource-Aware": "Res.-Aw.",
         "Utility-Based": "Utility", "AMC-Adapted": "AMC-insp.",
         "Elastic-MC": "EMC-insp.", "Proposed-v1": "Prop.-v1",
         "Proposed": "Proposed", "RH-DP": "RH-DP",
         "RH-DP-Oracle": "RH-DP-Or."}
SCEN_SHORT = {"Normal": "Normal", "Network Degradation": "Net. degr.",
              "Edge Overload": "Edge overl.", "Cloud Failure": "Cloud fail.",
              "Resource Pressure": "Res. press.",
              "Emergency Mission": "Emergency",
              "Severe Degradation": "Severe degr.", "Recovery": "Recovery"}
SCEN_ABBR = {"Normal": "Norm.", "Network Degradation": "Net.",
             "Edge Overload": "Edge", "Cloud Failure": "Cloud",
             "Resource Pressure": "Res.", "Emergency Mission": "Emerg.",
             "Severe Degradation": "Sev.", "Recovery": "Rec."}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.family": "serif", "font.size": 7.5, "axes.titlesize": 8,
    "axes.labelsize": 7.5, "legend.fontsize": 6.5, "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.5, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "savefig.dpi": 300, "pdf.fonttype": 42,
})
COL_W = 3.5


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, name + ".pdf"), bbox_inches="tight")
    fig.savefig(os.path.join(OUT, name + ".png"), bbox_inches="tight", dpi=200)
    plt.close(fig)


def ci(v):
    v = np.asarray(v, float)
    return stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / np.sqrt(len(v))


def fig_utility_time(wl, compact=False):
    per = (wl.groupby(["policy", "trial", "t"])["utility_delivered"].sum()
           .reset_index())
    fig, ax = plt.subplots(figsize=(COL_W, 1.9) if compact
                           else (COL_W * 2, 2.3))
    for s in range(0, config.NUM_STEPS, 20):
        ax.axvspan(s - 0.5, s + 9.5, color="#f3f2ee", lw=0, zorder=0)
    for i, sc in enumerate(config.SCENARIO_ORDER):
        ax.text(i * 10 + 4.5, 452, (SCEN_ABBR if compact else SCEN_SHORT)[sc],
                ha="center", va="bottom", fontsize=5.5 if compact else 6,
                color=INK2)
    for p in PLOT_POLICIES:
        g = per[per["policy"] == p].groupby("t")["utility_delivered"]
        m = g.mean()
        h = g.apply(ci)
        col, mk, ls = STYLE[p]
        ax.plot(m.index, m.values, color=col, ls=ls, lw=1.4 if p == "Proposed"
                else 1.0, marker=mk, markevery=(5, 10), ms=3.5, label=DISPLAY.get(p, p),
                zorder=3 if p == "Proposed" else 2)
        ax.fill_between(m.index, m - h, m + h, color=col, alpha=0.15, lw=0)
    ax.set_xlim(-0.5, config.NUM_STEPS - 0.5)
    ax.set_ylim(0, 470)
    ax.set_xlabel("Decision step $t$")
    ax.set_ylabel("Delivered mission utility per step")
    if compact:
        ax.set_ylabel("Utility per step")
        ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.27),
                  frameon=False, fontsize=5.5, columnspacing=0.8,
                  handlelength=2.0)
        save(fig, "fig_utility_time_col")
        return
    ax.legend(ncol=7, loc="upper center", bbox_to_anchor=(0.5, -0.22),
              frameon=False)
    save(fig, "fig_utility_time")


def fig_critical(tm, wl):
    crit = wl[wl["critical"]]
    share = (crit.groupby("policy")["outcome"].value_counts(normalize=True)
             .unstack(fill_value=0.0))
    pols = [p for p in ALL_POLICIES if p in share.index]
    fig, ax = plt.subplots(figsize=(COL_W, 2.4))
    full = (crit.assign(f=(crit["outcome"] == "ok") & (crit["mode"] == "Full"))
            .groupby("policy")["f"].mean())
    parts = [
        ("Success, Full mode", full, "#6250d6", None),
        ("Success, degraded mode", share.get("ok") - full, "#a99ff0", None),
        ("Admitted, missed (resource overrun)", share.get("resource"),
         "#eb6834", None),
        ("No feasible onboard action", share.get("infeasible"), "#52514e",
         "////"),
    ]
    x = np.arange(len(pols))
    bottom = np.zeros(len(pols))
    for label, series, col, hatch in parts:
        if series is None:
            continue
        vals = np.array([series.get(p, 0.0) for p in pols]) * 100
        ax.bar(x, vals, bottom=bottom, color=col, width=0.7, label=label,
               edgecolor="white", linewidth=0.6, hatch=hatch)
        bottom += vals
    ns = tm.groupby("policy")["crit_non_suspension"].mean()
    ax.scatter(x, [ns[p] * 100 for p in pols], marker="_", s=120, color=INK,
               zorder=4, label="Non-suspension rate (old metric)")
    ax.set_xticks(x, [SHORT[p] for p in pols], rotation=40, ha="right")
    ax.set_ylim(0, 101)
    ax.set_ylabel("Critical workload-steps (%)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.38), ncol=2,
              frameon=False)
    save(fig, "fig_critical")


LABEL_OFFSET = {"QoS-Based": None, "Resource-Aware": None,
                "Utility-Based": (-4, -11), "RH-DP-Oracle": None,
                "RH-DP": (-62, 5), "Elastic-MC": (-46, 2), "Proposed": (5, 4),
                "MDP-Migration": (6, -9)}
LABEL_TEXT = {"Utility-Based": "QoS / Res.-Aw. / Utility",
              "RH-DP": "RH-DP, RH-DP-Or."}


def fig_cost_benefit(tm):
    fig, axes = plt.subplots(1, 2, figsize=(COL_W * 2, 2.1))
    lat = pd.read_csv(os.path.join(RES, "runtime",
                                   "decision_latency_repeated.csv"))
    pols = [p for p in ALL_POLICIES if p in set(lat["policy"])]
    ax = axes[0]
    data = lat.set_index("policy").loc[pols]
    y = np.arange(len(pols))
    for i, p in enumerate(pols):
        col = STYLE[p][0]
        r = data.loc[p]
        ax.plot([r["min_us"], r["max_us"]], [i, i], color=col, lw=0.8)
        ax.plot([r["median_us"], r["p95_us"]], [i, i], color=col, lw=3,
                solid_capstyle="butt")
        ax.plot(r["mean_us"], i, marker=STYLE[p][1], color=col, ms=5,
                markeredgecolor="white", markeredgewidth=0.5)
    ax.set_xscale("log")
    ax.set_yticks(y, [SHORT[p] for p in pols])
    ax.invert_yaxis()
    ax.set_xlabel(r"Decision time per step ($\mu$s, log)")
    ax.set_title("(a) min-max, median-p95 (bar), mean (marker)", loc="left")
    ax = axes[1]
    for p in [q for q in ALL_POLICIES if q in set(tm["policy"])]:
        g = tm[tm["policy"] == p]
        col, mk, _ = STYLE[p]
        xm = data.loc[p, "mean_us"]
        ym, h = g["utility_delivered"].mean(), ci(g["utility_delivered"])
        ax.errorbar(xm, ym, yerr=h, fmt=mk, color=col, ms=5, capsize=2,
                    lw=0.8,
                    markeredgecolor=(col if mk in "x+" else "white"),
                    markeredgewidth=(1.2 if mk in "x+" else 0.5))
        off = LABEL_OFFSET.get(p, (4, 2))
        if off is not None:
            ax.annotate(LABEL_TEXT.get(p, SHORT[p]), (xm, ym), xytext=off,
                        textcoords="offset points", fontsize=6, color=INK2)
    ax.set_xscale("log")
    ax.set_xlabel(r"Mean decision time ($\mu$s, log)")
    ax.set_ylabel("Delivered utility per mission")
    ax.set_title("(b) utility (mean $\\pm$95% CI) vs. decision cost",
                 loc="left")
    fig.tight_layout(w_pad=2)
    save(fig, "fig_cost_benefit")


def fig_sensitivity():
    path = os.path.join(RES, "sensitivity", "sensitivity_summary.csv")
    if not os.path.exists(path):
        return
    s = pd.read_csv(path, dtype={"value": str})
    fig, axes = plt.subplots(1, 3, figsize=(COL_W * 2, 2.0))
    ax = axes[0]
    n = s[s["sweep"] == "noise"].copy()
    n["v"] = n["value"].astype(float)
    for p in ["Static", "Utility-Based", "AMC-Adapted", "Elastic-MC",
              "Proposed-v1", "Proposed", "RH-DP"]:
        g = n[n["policy"] == p].sort_values("v")
        if g.empty:
            continue
        col, mk, ls = STYLE[p]
        ax.errorbar(g["v"], g["utility_delivered"],
                    yerr=g["utility_delivered_ci95"], color=col, marker=mk,
                    ls=ls, ms=3.5, lw=1, capsize=1.5, label=SHORT[p])
    ax.set_xlabel("Noise intensity multiplier")
    ax.set_ylabel("Delivered utility per mission")
    ax.set_title("(a) stochastic intensity", loc="left")
    ax.set_ylim(14300, None)
    ax.legend(frameon=False, fontsize=5.3, ncol=2, loc="lower left",
              columnspacing=0.8, handlelength=2.2)
    ax = axes[1]
    m = s[s["sweep"] == "margin"].copy()
    m["v"] = m["value"].astype(float)
    for j, p in enumerate(["AMC-Adapted", "Elastic-MC", "Proposed"]):
        g = m[m["policy"] == p].sort_values("v")
        col, mk, ls = STYLE[p]
        ax.errorbar(g["v"] + (j - 1) * 0.006, g["crit_exec_success"] * 100,
                    yerr=g["crit_exec_success_ci95"] * 100, color=col,
                    marker=mk, ls=ls, ms=3.5, lw=1, capsize=1.5,
                    label=SHORT[p])
    ax.set_xticks([0.0, 0.1, 0.2])
    ax.set_xlabel("HI-budget headroom $\\delta$")
    ax.set_ylabel("Critical execution success (%)")
    ax.set_title("(b) HI-budget headroom", loc="left")
    ax.legend(frameon=False, fontsize=5.5, loc="lower right")
    ax = axes[2]
    h = s[(s["sweep"] == "horizon")].copy()
    h["v"] = h["value"].astype(int)
    h = h.sort_values("v")
    col = STYLE["RH-DP"][0]
    ax.errorbar(h["decision_us_mean"] / 1000.0, h["utility_delivered"],
                yerr=h["utility_delivered_ci95"], marker="P", color=col,
                lw=1, ms=3.5, capsize=1.5, label="RH-DP")
    for _, r in h.iterrows():
        ax.annotate(f"H={r['v']}", (r["decision_us_mean"] / 1000.0,
                                    r["utility_delivered"]),
                    xytext=(-6, 9 if r["v"] % 2 else -14),
                    textcoords="offset points", fontsize=5.5, color=INK2)
    main = pd.read_csv(os.path.join(RES, "main", "trial_metrics.csv"))
    pm = main[main["policy"] == "Proposed"]
    lat = pd.read_csv(os.path.join(RES, "main", "decision_latency.csv"))
    px = lat.set_index("policy").loc["Proposed", "mean_us"] / 1000.0
    ax.errorbar([px], [pm["utility_delivered"].mean()],
                yerr=[ci(pm["utility_delivered"])], marker="o",
                color=STYLE["Proposed"][0], ms=3.5, capsize=1.5,
                label="Proposed (one-step)")
    ylo = h["utility_delivered"].min() - 400
    ax.set_ylim(ylo, ylo + 800)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter("%g"))
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xticks([0.3, 1, 3, 10])
    ax.set_xlabel("Mean decision time (ms, log)")
    ax.set_ylabel("Delivered utility per mission")
    ax.set_title("(c) look-ahead horizon $H$", loc="left")
    ax.legend(frameon=False, fontsize=5.5, loc="lower right")
    fig.tight_layout(w_pad=1.2)
    save(fig, "fig_sensitivity")


def main():
    d = os.path.join(RES, "main")
    wl = pd.read_csv(os.path.join(d, "workload_log.csv.gz"))
    wl["mode"] = wl["mode"].fillna("")
    wl["location"] = wl["location"].fillna("")
    tm = pd.read_csv(os.path.join(d, "trial_metrics.csv"))
    fig_utility_time(wl)
    fig_utility_time(wl, compact=True)
    fig_critical(tm, wl)
    if os.path.exists(os.path.join(RES, "runtime",
                                   "decision_latency_repeated.csv")):
        fig_cost_benefit(tm)
    fig_sensitivity()
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
