"""
Generate every LaTeX table and every in-text number of the revised paper
from config.py, the policy code and results/.  Output: paper/generated/*.tex

    python -m experiments.make_tables
"""

import json
import math
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
RES = os.path.join(ROOT, "results")
OUT = os.environ.get("TAB_DIR", os.path.join(ROOT, "generated"))

import config  # noqa: E402
from models.mission import MissionPhase  # noqa: E402
from models.workload import ExecutionMode  # noqa: E402
from orchestrator.utility import MISSION_IMPORTANCE, QUALITY_FACTOR  # noqa: E402
from simulation.environment import scenario_targets  # noqa: E402

POL = ["Static", "QoS-Based", "Resource-Aware", "Utility-Based",
       "AMC-Adapted", "Elastic-MC", "MDP-Migration", "Proposed-v1", "Proposed", "RH-DP",
       "RH-DP-Oracle"]
MACROS = {}


def macro(name, value):
    MACROS[name] = value


def w(name, text):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name + ".tex"), "w") as fh:
        fh.write(text)


def fmt(x, nd=1):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "--"
    return f"{x:,.{nd}f}".replace(",", "{,}")


def pm(m, h, nd=1, scale=1.0):
    return f"{fmt(m * scale, nd)}$\\pm${fmt(h * scale, nd)}"


DISPLAY = {"AMC-Adapted": "AMC-inspired", "Elastic-MC": "EMC-inspired"}


def pname(p):
    return {"Proposed": "\\textbf{Proposed}"}.get(p, DISPLAY.get(p, p))


# ------------------------------------------------------------- parameters --
def tab_workloads():
    rows = []
    for s in config.WORKLOAD_SPECS:
        loc = ("$\\{O\\}$" if s["name"] in config.SAFETY_ONBOARD_ONLY
               else "$\\{O,E_1,E_2,C\\}$")
        crit = {"VERY_HIGH": "Very high (5)", "HIGH": "High (4)",
                "MEDIUM": "Medium (3)", "LOW": "Low (1)"}[s["criticality"]]
        rows.append(f"{s['name']} & {crit} & {s['cpu']} & {s['memory']} & "
                    f"{s['energy']} & {s['deadline']} & {s['network']} & "
                    f"{s['state_mb']:g} & {loc} \\\\")
    w("tab_workloads", "\n".join(rows) + "\n")


def tab_phase_matrix():
    phases = [MissionPhase.TAKEOFF, MissionPhase.CRUISE, MissionPhase.APPROACH,
              MissionPhase.LANDING, MissionPhase.EMERGENCY]
    modes = [ExecutionMode.FULL, ExecutionMode.REDUCED, ExecutionMode.FALLBACK]
    rows = []
    for s in config.WORKLOAD_SPECS:
        n = s["name"]
        b = " & ".join(str(MISSION_IMPORTANCE[n][p]) for p in phases)
        q = " & ".join(f"{QUALITY_FACTOR[n][m]:.2f}" for m in modes)
        rows.append(f"{n} & {b} & {q} \\\\")
    w("tab_phase_matrix", "\n".join(rows) + "\n")


def tab_scenarios():
    rows = []
    prof = config.PHASE_PROFILES["flight"]
    for i, sc in enumerate(config.SCENARIO_ORDER):
        t = scenario_targets(sc)
        pgb, pbg = config.GE_LINK[sc]
        cloud = "up" if t["cloud_up"] else "down"
        rows.append(
            f"{i*10}--{i*10+9} & {sc} & {prof[sc].title()} & "
            f"{t['onboard_cpu']:g}/{t['onboard_energy']:g} & "
            f"{t['e1_cpu']:g}/{t['e2_cpu']:g} & {cloud} & "
            f"{t['latency']:g}/{t['bandwidth']:g}/{t['loss']:g} & "
            f"{pgb:.2f}/{pbg:.2f} \\\\")
    w("tab_scenarios", "\n".join(rows) + "\n")


# ---------------------------------------------------------------- results --
def summary(tag):
    s = pd.read_csv(os.path.join(RES, tag, "summary.csv"))
    mean = s.pivot(index="policy", columns="metric", values="mean")
    ci = s.pivot(index="policy", columns="metric", values="ci95")
    return mean, ci


def tab_overall():
    mean, ci = summary("main")
    tests = pd.read_csv(os.path.join(RES, "main", "paired_tests.csv"))
    sig = {}
    for _, r in tests.iterrows():
        sig[(r["metric"], r["other"])] = r["p_holm"] < 0.05
    rows = []
    for p in POL:
        if p not in mean.index:
            continue
        def cell(metric, nd, scale=1.0):
            star = ("$^{\\ast}$" if sig.get((metric, p)) else "")
            return pm(mean.loc[p, metric], ci.loc[p, metric], nd, scale) + star
        rows.append(" & ".join([
            pname(p),
            cell("utility_delivered", 0),
            cell("crit_exec_success", 1, 100),
            fmt(mean.loc[p, "crit_non_suspension"] * 100, 1),
            fmt(mean.loc[p, "crit_full_rate"] * 100, 1),
            cell("deadline_miss_ratio", 1, 100),
            cell("completion_rate", 1, 100),
            fmt(mean.loc[p, "infeasible_count"], 1),
        ]) + " \\\\")
    w("tab_overall", "\n".join(rows) + "\n")

    rows = []
    for p in POL:
        if p not in mean.index:
            continue
        rows.append(" & ".join([
            pname(p),
            pm(mean.loc[p, "migrations"], ci.loc[p, "migrations"], 1),
            fmt(mean.loc[p, "migration_overhead_ms"] / 1000.0, 2),
            fmt(mean.loc[p, "fallbacks"], 1),
            fmt(mean.loc[p, "suspensions"], 1),
            pm(mean.loc[p, "energy_total"], ci.loc[p, "energy_total"], 0),
            fmt(mean.loc[p, "energy_onboard"], 0),
            fmt(mean.loc[p, "onboard_cpu_util"] * 100, 1),
            fmt(mean.loc[p, "onboard_mem_util"] * 100, 1),
            fmt(mean.loc[p, "edge_cpu_util"] * 100, 1),
        ]) + " \\\\")
    w("tab_adaptation", "\n".join(rows) + "\n")

    for p in POL:
        if p not in mean.index:
            continue
        key = p.replace("-", "").replace(" ", "")
        macro(f"U{key}", fmt(mean.loc[p, "utility_delivered"], 0))
        macro(f"UCI{key}", fmt(ci.loc[p, "utility_delivered"], 0))
        macro(f"Crit{key}", fmt(mean.loc[p, "crit_exec_success"] * 100, 1))
        macro(f"NonSusp{key}", fmt(mean.loc[p, "crit_non_suspension"] * 100, 1))
        macro(f"CritFull{key}", fmt(mean.loc[p, "crit_full_rate"] * 100, 1))
        macro(f"Miss{key}", fmt(mean.loc[p, "deadline_miss_ratio"] * 100, 1))
        macro(f"Compl{key}", fmt(mean.loc[p, "completion_rate"] * 100, 1))
        macro(f"Mig{key}", fmt(mean.loc[p, "migrations"], 1))
        macro(f"MigMs{key}", fmt(mean.loc[p, "migration_overhead_ms"] / 1000, 2))
        macro(f"Energy{key}", fmt(mean.loc[p, "energy_total"], 0))
        macro(f"Infeas{key}", fmt(mean.loc[p, "infeasible_count"], 1))
        macro(f"Plan{key}", fmt(mean.loc[p, "utility_planned"], 0))

    for _, r in tests.iterrows():
        key = r["other"].replace("-", "").replace(" ", "")
        mkey = {"utility_delivered": "U", "crit_exec_success": "Crit",
                "deadline_miss_ratio": "Miss", "completion_rate": "Compl",
                "energy_total": "Energy", "migrations": "Mig",
                "migration_overhead_ms": "MigMs"}[r["metric"]]
        scale = 100 if mkey in ("Crit", "Miss", "Compl") else 1
        nd = 1 if scale == 100 else (0 if mkey in ("U", "Energy") else 1)
        if mkey == "MigMs":
            scale, nd = 0.001, 2
        macro(f"D{mkey}{key}", fmt(r["mean_diff"] * scale, nd))
        macro(f"Abs{mkey}{key}", fmt(abs(r["mean_diff"]) * scale, nd))
        macro(f"DCI{mkey}{key}", fmt(r["ci95"] * scale, nd))
        p = r["p_holm"]
        macro(f"P{mkey}{key}", "<0.001" if p < 0.001 else f"={p:.3f}")
        macro(f"W{mkey}{key}", f"{int(r['wins'])}/{int(r['ties'])}/{int(r['losses'])}")


def tab_scenario_utility():
    sc = pd.read_csv(os.path.join(RES, "main", "scenario_summary.csv"))
    piv = sc.pivot(index="policy", columns="scenario", values="mean")
    cols = config.SCENARIO_ORDER
    rows = []
    for p in ["Static", "Utility-Based", "AMC-Adapted", "Elastic-MC",
              "Proposed-v1", "Proposed", "RH-DP"]:
        best = {c: piv[c].max() for c in cols}
        cells = []
        for c in cols:
            v = piv.loc[p, c]
            txt = fmt(v, 0)
            cells.append(f"\\textbf{{{txt}}}" if abs(v - best[c]) < 0.5 else txt)
        rows.append(pname(p) + " & " + " & ".join(cells) + " \\\\")
    w("tab_scenario_utility", "\n".join(rows) + "\n")
    for p in ["Proposed", "Elastic-MC", "Utility-Based", "Proposed-v1",
              "AMC-Adapted", "Static"]:
        key = p.replace("-", "")
        macro(f"RP{key}", fmt(piv.loc[p, "Resource Pressure"], 0))
        macro(f"SD{key}", fmt(piv.loc[p, "Severe Degradation"], 0))


def tab_emergency():
    em = pd.read_csv(os.path.join(RES, "main", "emergency_summary.csv"))
    ew = pd.read_csv(os.path.join(RES, "main", "emergency_per_workload.csv"))
    leg = pd.read_csv(os.path.join(RES, "legacy", "emergency_summary.csv"))
    rows = []
    for p in POL:
        r = em[em["policy"] == p].iloc[0]
        l = leg[leg["policy"] == p].iloc[0]
        v = ew[(ew["policy"] == p) & (ew["workload"] == "Video Analytics")].iloc[0]
        wa = ew[(ew["policy"] == p) & (ew["workload"] == "Weather Analysis")].iloc[0]
        rows.append(" & ".join([
            pname(p), fmt(l["utility_delivered"], 0),
            pm(r["utility_delivered"], r["utility_delivered_ci95"], 0),
            fmt(r["crit_exec_success"] * 100, 1),
            fmt(r["crit_full_rate"] * 100, 1),
            fmt(v["utility_mean"], 0), fmt(v["share_full"] * 100, 0),
            fmt(wa["utility_mean"], 0),
            fmt(r["migrations"], 1),
        ]) + " \\\\")
        key = p.replace("-", "")
        macro(f"EmLeg{key}", fmt(l["utility_delivered"], 0))
        macro(f"Em{key}", fmt(r["utility_delivered"], 0))
        macro(f"EmVideo{key}", fmt(v["utility_mean"], 0))
        macro(f"EmVideoFull{key}", fmt(v["share_full"] * 100, 0))
    w("tab_emergency", "\n".join(rows) + "\n")


def tab_runtime():
    rt = pd.read_csv(os.path.join(RES, "runtime", "decision_latency_repeated.csv"))
    rows = []
    for p in POL:
        r = rt[rt["policy"] == p]
        if r.empty:
            continue
        r = r.iloc[0]
        rows.append(" & ".join([
            pname(p), f"{int(r['samples']):,}".replace(",", "{,}"),
            fmt(r["mean_us"], 0), fmt(r["min_us"], 0),
            fmt(r["median_us"], 0), fmt(r["p95_us"], 0),
            fmt(r["max_us"], 0)]) + " \\\\")
        key = p.replace("-", "")
        macro(f"Lat{key}", fmt(r["mean_us"], 0))
        macro(f"LatP{key}", fmt(r["p95_us"], 0))
        macro(f"LatMax{key}", fmt(r["max_us"], 0))
        macro(f"LatMs{key}", fmt(r["mean_us"] / 1000.0, 2))
    w("tab_runtime", "\n".join(rows) + "\n")
    macro("LatRatioDP", fmt(
        rt.set_index("policy").loc["RH-DP", "mean_us"]
        / rt.set_index("policy").loc["Proposed", "mean_us"], 0))

    cnt = pd.read_csv(os.path.join(RES, "runtime", "combination_counts.csv"))
    pc = cnt[cnt["policy"] == "Proposed"]
    for k in ("phase1_evaluated", "phase1_feasible", "phase2_evaluated",
              "phase2_feasible", "catalogue_actions"):
        macro("Cnt" + k.replace("_", "").title().replace("Phase", "Ph"),
              f"{pc[k].mean():.1f}")
        macro("CntMax" + k.replace("_", "").title().replace("Phase", "Ph"),
              f"{pc[k].max():.0f}")
        macro("CntMin" + k.replace("_", "").title().replace("Phase", "Ph"),
              f"{pc[k].min():.0f}")
    dc = cnt[cnt["policy"] == "RH-DP"]
    macro("CntDPNodes", fmt(dc["nodes_feasible"].mean(), 0))
    macro("CntDPTrans", fmt(dc["transitions"].mean(), 0))

    asp = pd.read_csv(os.path.join(RES, "runtime", "action_space.csv"))
    names = ["ASUnrestricted", "ASOriginal", "ASRevised", "ASScreened",
             "ASPhaseOne", "ASPhaseTwo"]
    for n, v in zip(names, asp["value"]):
        macro(n, f"{int(v):,}".replace(",", "{,}"))

    sc = pd.read_csv(os.path.join(RES, "runtime", "scaling.csv"))
    rows = []
    for n_c in sorted(sc["n_critical"].unique()):
        g = sc[sc["n_critical"] == n_c].set_index("n_noncritical")
        rows.append(f"{n_c} & {int(g['phase1_evaluated'].iloc[0])} & " +
                    " & ".join(fmt(g.loc[n, 'mean_us'], 0)
                               for n in sorted(g.index)) + " \\\\")
    w("tab_scaling", "\n".join(rows) + "\n")
    env = open(os.path.join(RES, "runtime", "environment.txt")).read()
    macro("BenchReps", env.split("repetitions ")[1].split()[0])


def sensitivity_macros():
    s = pd.read_csv(os.path.join(RES, "sensitivity", "sensitivity_summary.csv"),
                    dtype={"value": str})

    def get(sweep, value, policy, metric):
        r = s[(s["sweep"] == sweep) & (s["value"] == value)
              & (s["policy"] == policy)]
        return float(r[metric].iloc[0])

    for v, tag in (("0.0", "Zero"), ("0.1", "One"), ("0.2", "Two")):
        for p in ("Proposed", "Elastic-MC", "AMC-Adapted"):
            k = p.replace("-", "")
            macro(f"Mar{tag}Crit{k}",
                  fmt(get("margin", v, p, "crit_exec_success") * 100, 1))
            macro(f"Mar{tag}U{k}", fmt(get("margin", v, p, "utility_delivered"), 0))
            macro(f"Mar{tag}Full{k}",
                  fmt(get("margin", v, p, "crit_full_rate") * 100, 1))
    for v, tag in (("0.0", "Zero"), ("2.0", "Two")):
        for p in ("Proposed", "Elastic-MC", "Utility-Based", "RH-DP"):
            k = p.replace("-", "")
            macro(f"Noise{tag}U{k}", fmt(get("noise", v, p, "utility_delivered"), 0))
    for v in ("1", "2", "3", "5", "8"):
        macro(f"HorU{['','One','Two','Three','','Five','','','Eight'][int(v)]}",
              fmt(get("horizon", v, "RH-DP", "utility_delivered"), 0))
        macro(f"HorLat{['','One','Two','Three','','Five','','','Eight'][int(v)]}",
              fmt(get("horizon", v, "RH-DP", "decision_us_mean") / 1000, 1))
    for v, tag in (("6.0", "Six"), ("8.0", "Eight"), ("inf", "Inf")):
        for p in ("Proposed", "Elastic-MC"):
            k = p.replace("-", "")
            macro(f"Cov{tag}U{k}", fmt(get("coverage", v, p, "utility_delivered"), 0))
    for v, tag in (("flight", "Flight"), ("cruise_only", "Cruise")):
        for p in ("Proposed", "Elastic-MC", "Proposed-v1"):
            k = p.replace("-", "")
            macro(f"Prof{tag}U{k}", fmt(get("profile", v, p, "utility_delivered"), 0))
    for v, tag in (("False", "Live"), ("True", "Cold")):
        for p in ("Proposed", "Elastic-MC", "Utility-Based"):
            k = p.replace("-", "")
            macro(f"Mig{tag}U{k}", fmt(get("cold_mig", v, p, "utility_delivered"), 0))
            macro(f"Mig{tag}N{k}", fmt(get("cold_mig", v, p, "migrations"), 1))
    for v, tag in (("10.0", "Ten"), ("100.0", "Hundred")):
        for p in ("Proposed", "Elastic-MC", "Proposed-v1"):
            k = p.replace("-", "")
            macro(f"Bw{tag}U{k}", fmt(get("mig_bw", v, p, "utility_delivered"), 0))

    rows = []
    sweeps = [("noise", "0.0", "Noise $\\times$0 (deterministic)"),
              ("noise", "2.0", "Noise $\\times$2"),
              ("coverage", "6.0", "Coverage $R=6$ km"),
              ("coverage", "inf", "Coverage $R=\\infty$ (orig.)"),
              ("profile", "cruise_only", "Cruise-only phases (orig.)"),
              ("cold_mig", "True", "Cold migration ($T^{mig}$ in $D_i$)"),
              ("mig_bw", "10.0", "$B^{mig}=10$ MB/s")]
    cols = ["Utility-Based", "AMC-Adapted", "Elastic-MC", "Proposed-v1",
            "Proposed"]
    for sw, v, label in sweeps:
        vals = [get(sw, v, p, "utility_delivered") for p in cols]
        best = max(vals)
        cells = [(f"\\textbf{{{fmt(x, 0)}}}" if abs(x - best) < 0.5
                  else fmt(x, 0)) for x in vals]
        rows.append(label + " & " + " & ".join(cells) + " \\\\")
    w("tab_sensitivity", "\n".join(rows) + "\n")


def manifest_macros():
    m = json.load(open(os.path.join(RES, "main", "manifest.json")))
    macro("NumTrials", str(m["trials"]))
    macro("BaseSeed", str(config.BASE_SEED))
    macro("NumSteps", str(config.NUM_STEPS))
    macro("PyVersion", m["python"].split()[0])


def legacy_macros():
    mean, _ = summary("legacy")
    for p in POL:
        key = p.replace("-", "")
        macro(f"LegU{key}", fmt(mean.loc[p, "utility_delivered"], 0))
        macro(f"LegCrit{key}", fmt(mean.loc[p, "crit_exec_success"] * 100, 2))
        macro(f"LegNonSusp{key}",
              fmt(mean.loc[p, "crit_non_suspension"] * 100, 2))


# ------------------------------------------------- compact (6-page) tables --
COMPACT = ["Static", "Utility-Based", "AMC-Adapted", "Elastic-MC",
           "MDP-Migration", "Proposed-v1", "Proposed", "RH-DP"]
SHORTN = {"Utility-Based": "Utility$^{\\dagger}$", "AMC-Adapted": "AMC-inspired",
          "Elastic-MC": "EMC-inspired", "MDP-Migration": "MDP-Migration", "Proposed-v1": "Proposed-v1",
          "Proposed": "\\textbf{Proposed}", "RH-DP": "RH-DP$^{\\ddagger}$",
          "Static": "Static"}


def tab_compact():
    mean, ci = summary("main")
    tests = pd.read_csv(os.path.join(RES, "main", "paired_tests.csv"))
    sig = {(r["metric"], r["other"]): r["p_holm"] < 0.05
           for _, r in tests.iterrows()}
    rt = pd.read_csv(os.path.join(RES, "runtime",
                                  "decision_latency_repeated.csv")).set_index("policy")
    rows = []
    for p in COMPACT:
        def c(metric, nd, scale=1.0, with_ci=True):
            star = "$^{\\ast}$" if sig.get((metric, p)) else ""
            if with_ci:
                return pm(mean.loc[p, metric], ci.loc[p, metric], nd, scale) + star
            return fmt(mean.loc[p, metric] * scale, nd) + star
        rows.append(" & ".join([
            SHORTN[p], c("utility_delivered", 0),
            c("crit_exec_success", 1, 100),
            fmt(mean.loc[p, "crit_non_suspension"] * 100, 1),
            c("deadline_miss_ratio", 1, 100, False),
            c("completion_rate", 1, 100, False),
            fmt(mean.loc[p, "infeasible_count"], 1),
            c("migrations", 1, 1, False),
            fmt(mean.loc[p, "migration_overhead_ms"] / 1000.0, 1),
            c("energy_total", 0, 1, False),
            fmt(mean.loc[p, "onboard_cpu_util"] * 100, 1),
            fmt(mean.loc[p, "onboard_mem_util"] * 100, 1),
            fmt(rt.loc[p, "mean_us"], 0) + "/" + fmt(rt.loc[p, "p95_us"], 0),
        ]) + " \\\\")
    w("tab_compact_overall", "\n".join(rows) + "\n")

    em = pd.read_csv(os.path.join(RES, "main", "emergency_summary.csv"))
    ew = pd.read_csv(os.path.join(RES, "main", "emergency_per_workload.csv"))
    leg = pd.read_csv(os.path.join(RES, "legacy", "emergency_summary.csv"))
    rows = []
    for p in ["Utility-Based", "AMC-Adapted", "Elastic-MC", "MDP-Migration",
              "Proposed-v1", "Proposed"]:
        r = em[em["policy"] == p].iloc[0]
        l = leg[leg["policy"] == p].iloc[0]
        v = ew[(ew["policy"] == p) & (ew["workload"] == "Video Analytics")].iloc[0]
        rows.append(" & ".join([
            SHORTN[p].replace("$^{\\dagger}$", ""), fmt(l["utility_delivered"], 0),
            pm(r["utility_delivered"], r["utility_delivered_ci95"], 0),
            fmt(r["crit_exec_success"] * 100, 1),
            fmt(v["utility_mean"], 0), fmt(v["share_full"] * 100, 0)]) + " \\\\")
    w("tab_compact_emergency", "\n".join(rows) + "\n")

    rows = []
    for s_ in config.WORKLOAD_SPECS:
        n = s_["name"]
        phases = [MissionPhase.TAKEOFF, MissionPhase.CRUISE, MissionPhase.APPROACH,
                  MissionPhase.LANDING, MissionPhase.EMERGENCY]
        b = "/".join(str(MISSION_IMPORTANCE[n][ph]) for ph in phases)
        q = "/".join(f"{QUALITY_FACTOR[n][m]:.2f}".lstrip("0") for m in
                     (ExecutionMode.FULL, ExecutionMode.REDUCED,
                      ExecutionMode.FALLBACK))
        loc = "$O$" if n in config.SAFETY_ONBOARD_ONLY else "all"
        crit = {"VERY_HIGH": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 1}[s_["criticality"]]
        rows.append(f"{n} & {crit} & {s_['cpu']}/{s_['memory']}/{s_['energy']} & "
                    f"{s_['deadline']} & {s_['network']} & {loc} & {b} & {q} \\\\")
    w("tab_compact_workloads", "\n".join(rows) + "\n")


def tab_ablation():
    d = os.path.join(RES, "ablation")
    if not os.path.exists(os.path.join(d, "summary.csv")):
        return
    smy = pd.read_csv(os.path.join(d, "summary.csv"))
    mean = smy.pivot(index="policy", columns="metric", values="mean")
    ci = smy.pivot(index="policy", columns="metric", values="ci95")
    tests = pd.read_csv(os.path.join(d, "paired_tests.csv"))
    labels = [("Proposed", "Full policy"),
              ("Abl-NoJointAdmission", "-- joint critical admission"),
              ("Abl-NoDegradation", "-- service-mode degradation"),
              ("Abl-NoMigCost", "-- migration cost in objective"),
              ("Abl-FixedOrder", "-- phase-dependent order"),
              ("Abl-PhaseBlind", "-- phase awareness (all)")]
    rows = []
    for p, lab in labels:
        if p == "Proposed":
            d_u = "--"
        else:
            r = tests[(tests["metric"] == "utility_delivered")
                      & (tests["other"] == p)].iloc[0]
            # difference reported as variant minus full policy
            star = "$^{\\ast}$" if r["p_holm"] < 0.05 else ""
            d_u = fmt(-r["mean_diff"], 1) + star
            key = p.replace("Abl-", "").replace("-", "")
            macro(f"AblD{key}", fmt(-r["mean_diff"], 1))
            macro(f"AblLoss{key}", fmt(r["mean_diff"], 1))
            macro(f"AblP{key}", "<0.001" if r["p_holm"] < 0.001
                  else f"={r['p_holm']:.3f}")
            rm = tests[(tests["metric"] == "migrations") & (tests["other"] == p)].iloc[0]
            macro(f"AblDMig{key}", fmt(-rm["mean_diff"], 1))
            rc = tests[(tests["metric"] == "crit_exec_success") & (tests["other"] == p)].iloc[0]
            macro(f"AblDCrit{key}", fmt(-rc["mean_diff"] * 100, 1))
            macro(f"AblLossCrit{key}", fmt(rc["mean_diff"] * 100, 1))
        rows.append(" & ".join([
            lab, pm(mean.loc[p, "utility_delivered"], ci.loc[p, "utility_delivered"], 0),
            d_u, fmt(mean.loc[p, "crit_exec_success"] * 100, 1),
            fmt(mean.loc[p, "completion_rate"] * 100, 1),
            fmt(mean.loc[p, "migrations"], 1)]) + " \\\\")
    w("tab_ablation", "\n".join(rows) + "\n")


def write_macros():
    lines = ["% AUTO-GENERATED by experiments/make_tables.py -- do not edit"]
    seen = {}
    for k, v in sorted(MACROS.items()):
        k2 = k.replace("Ph1", "PhOne").replace("Ph2", "PhTwo").replace(
            "v1", "vOne")
        safe = "".join(ch for ch in k2 if ch.isalpha())
        assert safe not in seen, f"macro collision {k} vs {seen[safe]}"
        seen[safe] = k
        lines.append(f"\\newcommand{{\\R{safe}}}{{{v}}}")
    w("results_macros", "\n".join(lines) + "\n")


def main():
    tab_workloads()
    tab_phase_matrix()
    tab_scenarios()
    tab_overall()
    tab_scenario_utility()
    tab_emergency()
    tab_runtime()
    sensitivity_macros()
    manifest_macros()
    legacy_macros()
    tab_compact()
    tab_ablation()
    write_macros()
    print("tables and macros written to", OUT, f"({len(MACROS)} macros)")


if __name__ == "__main__":
    main()
