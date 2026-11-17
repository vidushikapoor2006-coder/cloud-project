"""
Mission-aware adaptive orchestration policy (revised; Algorithm 1 of the paper).

The policy solves, at every decision step t, the lexicographic problem of
Eq. (20) in two phases:

  Phase 1 (flight-critical workloads, jointly):
      maximise  ( n_served, sum_i U_i, min_i q_i, -sum_i C_i )
      over all combinations of onboard actions of the critical workloads,
      subject to the joint resource constraint (Eq. (12)).  A critical
      workload may be left unserved ONLY if no joint combination can serve
      it; it is then reported as infeasible (a degraded safety condition),
      never as suspended and never offloaded.

  Phase 2 (non-critical workloads, one at a time):
      workloads are visited in decreasing phase-dependent importance
      B_i(M_t) (ties: static criticality); each selects
          argmax_a ( U_i(a), S_i(a) - C^mig_i(a) )
      over feasible actions that fit into the resources left over by the
      already committed workloads.

Changes with respect to the original submission (kept in decision_v1.py):
  * The separate migration gate "score gain > C^mig" was removed.  It used a
    different criterion from the utility-first selection and blocked
    utility-improving migrations (Emergency-scenario loss).  Migration cost
    now enters the secondary key: when utility is unchanged, a migration is
    selected only if its migration-adjusted operating score is better; a
    migration that raises mission utility is not blocked by its cost.
  * Phase 2 is ordered by B_i(M_t) rather than static criticality, so
    emergency-specific priorities are enforced.
  * Phase 1 includes a "served count" key, which replaces the original
    cost-only greedy fallback branch.
  * Optional instrumentation: number of evaluated / feasible combinations.
"""

from itertools import product

import config

from models.workload import Criticality, ExecutionMode

from orchestrator.feasibility import (
    get_feasible_actions, estimate_latency, generate_actions,
)
from orchestrator.utility import (
    calculate_score, calculate_utility, QUALITY_FACTOR, MISSION_IMPORTANCE,
)
from orchestrator.resource_manager import can_allocate, allocate
from orchestrator.runtime import update_workload_state
from orchestrator.history import classify_adaptation
from orchestrator.migration import calculate_migration_cost, is_migration


def _critical_workload(workload):
    """Mission-critical workloads are explicitly marked VERY_HIGH."""
    return workload.criticality == Criticality.VERY_HIGH


def _scored(workload, location, mode, system):
    """Operating score with migration overhead (S_i - C^mig_i)."""
    result = calculate_score(workload, location, mode, system)
    migration = calculate_migration_cost(
        workload, workload.current_location, location, system
    )
    result["migration_time_ms"] = migration["migration_time_ms"]
    result["migration_cost"] = migration["migration_cost"]
    result["migrated"] = is_migration(workload, location)
    result["base_score"] = result["score"]
    result["score"] = result["score"] - migration["migration_cost"]
    result["predicted_latency_ms"] = estimate_latency(
        workload, location, mode, system)
    return result


class _hi_budget:
    """Temporarily inflate CPU/energy demand to the HI budget (1+delta)c_i."""

    def __init__(self, workload, margin):
        self.w = workload
        self.margin = margin

    def __enter__(self):
        if self.margin:
            self.c, self.e = (self.w.compute_requirement,
                              self.w.energy_requirement)
            self.w.compute_requirement = self.c * (1.0 + self.margin)
            self.w.energy_requirement = self.e * (1.0 + self.margin)
        return self

    def __exit__(self, *exc):
        if self.margin:
            self.w.compute_requirement, self.w.energy_requirement = \
                self.c, self.e
        return False


def _select_critical_actions(critical_workloads, system, feasible, stats,
                             margin=None, allocations_out=None):
    """Phase 1: joint enumeration over critical onboard actions.

    With margin delta > 0 the critical workloads are admitted (and their
    capacity reserved) with the pessimistic budget (1 + delta) * c_i.
    """
    margin = config.CRITICAL_DEMAND_MARGIN if margin is None else margin
    option_lists = []
    for workload in critical_workloads:
        options = [
            action for action in feasible[workload.name]
            if action[1] != ExecutionMode.SUSPENDED
        ]
        # None = leave unserved (only chosen if nothing else fits).
        option_lists.append(options + [None])

    best = None
    for combination in product(*option_lists):
        stats["phase1_evaluated"] += 1
        allocations = {}
        ok = True
        n_served = 0
        total_utility = 0.0
        qualities = []
        total_cost = 0.0
        results = []
        for workload, action in zip(critical_workloads, combination):
            if action is None:
                results.append(None)
                continue
            location, mode = action
            with _hi_budget(workload, margin):
                fits = can_allocate(workload, location, mode, system,
                                    allocations)
                if fits:
                    allocate(workload, location, mode, allocations)
            if not fits:
                ok = False
                break
            result = _scored(workload, location, mode, system)
            n_served += 1
            total_utility += result["utility"]
            qualities.append(QUALITY_FACTOR[workload.name][mode])
            total_cost += (result["latency_cost"] + result["energy_cost"]
                           + result["resource_cost"]
                           + result["migration_cost"])
            results.append(result)
        if not ok:
            continue
        stats["phase1_feasible"] += 1
        key = (n_served, total_utility,
               min(qualities) if qualities else 0.0, -total_cost)
        if best is None or key > best["key"]:
            best = {"key": key, "combination": combination,
                    "results": results, "allocations": allocations}
    return best


def _sequential_critical(critical_workloads, system, feasible, stats):
    """Ablation: critical workloads admitted one at a time (no joint search);
    each takes lexmax (U, S) of what still fits."""
    allocations, combination, results = {}, [], []
    for workload in critical_workloads:
        cands = []
        for location, mode in feasible[workload.name]:
            stats["phase1_evaluated"] += 1
            if mode == ExecutionMode.SUSPENDED or not can_allocate(
                    workload, location, mode, system, allocations):
                continue
            stats["phase1_feasible"] += 1
            cands.append(((location, mode),
                          _scored(workload, location, mode, system)))
        if not cands:
            combination.append(None)
            results.append(None)
            continue
        action, result = max(cands, key=lambda c: (c[1]["utility"],
                                                    c[1]["score"]))
        allocate(workload, action[0], action[1], allocations)
        combination.append(action)
        results.append(result)
    return {"combination": combination, "results": results,
            "allocations": allocations}


def _commit_decision(workload, location, mode, result, allocations, decisions):
    """Apply a selected action and append a standard decision record."""
    old_location = workload.current_location
    old_mode = workload.current_mode

    update_workload_state(workload, location, mode)
    allocate(workload, location, mode, allocations)

    adapted = (old_location != location or old_mode != mode)
    adaptation_type = classify_adaptation(
        old_location.value, old_mode.value, location.value, mode.value
    )

    decisions.append({
        "workload": workload.name,
        "location": location,
        "mode": mode,
        "score": result["score"],
        "details": result,
        "adaptation_type": adaptation_type,
        "adapted": adapted,
    })


def _append_infeasible(workload, decisions):
    decisions.append({
        "workload": workload.name,
        "location": None,
        "mode": None,
        "score": None,
        "adapted": False,
    })


def phase2_order(workloads, mission_phase):
    """Non-critical visiting order: phase importance, then criticality."""
    return sorted(
        workloads,
        key=lambda w: (MISSION_IMPORTANCE[w.name][mission_phase],
                       w.criticality.value),
        reverse=True,
    )


ABLATION_DEFAULTS = {
    "phase_priority": True,    # Phase-2 order by B_i(M_t) (else static criticality)
    "phase_aware": True,       # decisions use the current phase (else fixed CRUISE weights)
    "joint_admission": True,   # Phase-1 joint enumeration (else sequential greedy)
    "migration_cost": True,    # C_mig in the secondary key (else ignored)
    "degradation": True,       # Reduced/Fallback modes allowed (else Full/Suspended only)
}


def select_actions_globally(system, stats=None, margin=None, ablation=None):
    """Mission-aware adaptive orchestration policy (Algorithm 1).

    Returns a list of decision records.  If ``stats`` is a dict it is filled
    with the number of evaluated and feasible combinations.  ``ablation``
    switches off individual components (component ablation study); the
    default is the full policy.
    """
    opts = dict(ABLATION_DEFAULTS, **(ablation or {}))
    if not opts["phase_aware"]:
        # Phase-blind variant: decide with fixed cruise importance; the true
        # phase is restored before the outcome is evaluated.
        from models.mission import MissionPhase
        true_phase = system.mission.phase
        system.mission.phase = MissionPhase.CRUISE
        try:
            return select_actions_globally(
                system, stats, margin, dict(opts, phase_aware=True))
        finally:
            system.mission.phase = true_phase
    if stats is None:
        stats = {}
    for key in ("phase1_evaluated", "phase1_feasible",
                "phase2_evaluated", "phase2_feasible"):
        stats[key] = 0
    # Number of catalogue actions screened by the hard-constraint filter.
    stats["catalogue_actions"] = sum(
        len(generate_actions(w)) for w in system.workloads
    )

    allocations = {}
    decisions = []

    # Feasible action sets, computed once per workload per step (cache).
    feasible = {
        w.name: get_feasible_actions(w, system) for w in system.workloads
    }
    if not opts["degradation"]:
        feasible = {n: [a for a in acts if a[1] in (ExecutionMode.FULL,
                                                     ExecutionMode.SUSPENDED)]
                    for n, acts in feasible.items()}

    critical_workloads = [w for w in system.workloads if _critical_workload(w)]
    noncritical_workloads = [
        w for w in system.workloads if not _critical_workload(w)
    ]

    # ------------------------------------------------------------
    # PHASE 1: Joint protection of mission-critical workloads
    # ------------------------------------------------------------
    if opts["joint_admission"]:
        best = _select_critical_actions(critical_workloads, system, feasible,
                                        stats, margin=margin)
    else:
        best = _sequential_critical(critical_workloads, system, feasible, stats)
    for workload, action, result in zip(
        critical_workloads, best["combination"], best["results"]
    ):
        if action is None:
            _append_infeasible(workload, decisions)
        else:
            _commit_decision(workload, action[0], action[1], result,
                             {}, decisions)
    # Reserve the (possibly HI-budget) capacity of the critical workloads so
    # that non-critical workloads cannot consume it.
    allocations = {k: dict(v) for k, v in best["allocations"].items()}

    # ------------------------------------------------------------
    # PHASE 2: Allocate remaining resources to non-critical work
    # ------------------------------------------------------------
    phase = system.mission.phase
    order = (phase2_order(noncritical_workloads, phase) if opts["phase_priority"]
             else sorted(noncritical_workloads,
                         key=lambda w: w.criticality.value, reverse=True))
    for workload in order:
        candidates = []
        for location, mode in feasible[workload.name]:
            stats["phase2_evaluated"] += 1
            if not can_allocate(workload, location, mode, system, allocations):
                continue
            stats["phase2_feasible"] += 1
            result = _scored(workload, location, mode, system)
            if not opts["migration_cost"]:
                result["score"] = result["base_score"]
            candidates.append((location, mode, result))

        if not candidates:
            _append_infeasible(workload, decisions)
            continue

        # Lexicographic key: mission utility first, then the operating
        # score net of migration overhead (Eq. (20)).
        best_candidate = max(
            candidates,
            key=lambda x: (x[2]["utility"], x[2]["score"]),
        )
        _commit_decision(workload, best_candidate[0], best_candidate[1],
                         best_candidate[2], allocations, decisions)

    return decisions
