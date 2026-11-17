"""
Literature-based baselines: adaptive mixed-criticality scheduling mapped to
the cloud-edge placement problem (Reviewer 2, comment 2).

1) AMC-Adapted  -- Adaptive Mixed Criticality, Baruah, Burns and Davis,
   "Response-time analysis for mixed criticality systems", RTSS 2011
   (dual-criticality model of Vestal, RTSS 2007).

   Original principles:
     * tasks have a criticality level (LO or HI);
     * the system starts in LO mode, in which every task runs with its
       LO-criticality budget;
     * when a HI task cannot be guaranteed with its LO budget (overrun),
       the system switches to HI mode and all LO tasks are dropped so that
       HI tasks are guaranteed;
     * the system returns to LO mode when it is safe to do so.

   Mapping used here (documented in Section VI-C of the paper):
     * HI = {Obstacle Detection, Navigation} (criticality VERY_HIGH),
       LO = all other workloads;
     * mode-switch trigger: at the start of a step the HI workloads cannot
       be jointly admitted at Full service on the onboard computer;
     * LO mode: every workload is admitted at Full service in criticality
       order, each on the feasible location with the smallest estimated
       response time (the placement analogue of response-time analysis);
       a LO workload with no Full placement is dropped (suspended), since
       AMC has no degraded service levels;
     * HI mode: HI workloads receive the jointly feasible onboard
       combination that maximises (#served, sum of service ranks); all LO
       workloads are dropped (suspended);
     * return to LO mode at the next step at which the trigger is false
       (immediate return; this is favourable to the baseline).

2) Elastic-MC -- elastic mixed-criticality model, Su and Zhu, "An elastic
   mixed-criticality task model and its scheduling algorithm", DATE 2013.
   Same as AMC, except that LO workloads are not dropped: their service is
   elastically reduced (Full -> Reduced -> Fallback), in criticality order,
   and they are suspended only if even Fallback cannot be admitted.

What both baselines intentionally do NOT have (because the original methods
do not have it): mission-phase-dependent importance, utility-based ranking,
and migration-cost awareness.  They use the same feasibility layer, safety
restriction, workloads, traces and seeds as every other policy.
"""

from itertools import product

from models.workload import Criticality, ExecutionMode, Location
from orchestrator.feasibility import get_feasible_actions, estimate_latency
from orchestrator.resource_manager import can_allocate, allocate
from orchestrator.runtime import update_workload_state
from orchestrator.decision import _hi_budget

SERVICE_RANK = {
    ExecutionMode.FULL: 3,
    ExecutionMode.REDUCED: 2,
    ExecutionMode.FALLBACK: 1,
    ExecutionMode.SUSPENDED: 0,
}


def _is_hi(workload):
    return workload.criticality == Criticality.VERY_HIGH


class MixedCriticalityPolicy:

    def __init__(self, elastic=False, margin=0.0, name=None):
        self.elastic = elastic
        # Optional pessimistic HI budget (1 + margin) * c_i for HI workloads
        # (C(HI) of Vestal's model); 0 by default, swept in sensitivity.
        self.margin = margin
        self.name = name or ("Elastic-MC" if elastic else "AMC-Adapted")
        self.mode = "LO"
        self.mode_switches = 0

    def reset(self):
        self.mode = "LO"
        self.mode_switches = 0

    # ------------------------------------------------------------------
    def _hi_full_admissible(self, hi, system, feasible):
        allocations = {}
        for w in hi:
            full = [a for a in feasible[w.name] if a[1] == ExecutionMode.FULL]
            placed = False
            for loc, mode in sorted(
                    full, key=lambda a: estimate_latency(w, a[0], a[1], system)):
                with _hi_budget(w, self.margin):
                    if can_allocate(w, loc, mode, system, allocations):
                        allocate(w, loc, mode, allocations)
                        placed = True
                if placed:
                    break
            if not placed:
                return None
        return allocations

    def _hi_mode_selection(self, hi, system, feasible):
        options = []
        for w in hi:
            opts = [a for a in feasible[w.name]
                    if a[1] != ExecutionMode.SUSPENDED]
            options.append(opts + [None])
        best = None
        for combo in product(*options):
            allocations = {}
            ok = True
            served = 0
            rank = 0
            latency = 0.0
            for w, a in zip(hi, combo):
                if a is None:
                    continue
                with _hi_budget(w, self.margin):
                    fits = can_allocate(w, a[0], a[1], system, allocations)
                    if fits:
                        allocate(w, a[0], a[1], allocations)
                if not fits:
                    ok = False
                    break
                served += 1
                rank += SERVICE_RANK[a[1]]
                latency += estimate_latency(w, a[0], a[1], system)
            if not ok:
                continue
            key = (served, rank, -latency)
            if best is None or key > best[0]:
                best = (key, combo, allocations)
        return best[1], best[2]

    def _place_lo(self, w, system, feasible, allocations, allowed_modes):
        for mode in allowed_modes:
            cands = [a for a in feasible[w.name] if a[1] == mode]
            for loc, m in sorted(
                    cands, key=lambda a: estimate_latency(w, a[0], a[1], system)):
                if can_allocate(w, loc, m, system, allocations):
                    return (loc, m)
        return None

    def _suspend(self, w, system, feasible, allocations):
        """Drop a LO workload: suspended where its state currently resides."""
        susp = [a for a in feasible[w.name] if a[1] == ExecutionMode.SUSPENDED]
        if not susp:
            return None
        same = [a for a in susp if a[0] == w.current_location]
        return (same or susp)[0]

    # ------------------------------------------------------------------
    def decide(self, system, ctx=None):
        feasible = {w.name: get_feasible_actions(w, system)
                    for w in system.workloads}
        hi = [w for w in system.workloads if _is_hi(w)]
        lo = sorted([w for w in system.workloads if not _is_hi(w)],
                    key=lambda w: w.criticality.value, reverse=True)

        hi_alloc = self._hi_full_admissible(hi, system, feasible)
        new_mode = "LO" if hi_alloc is not None else "HI"
        if new_mode != self.mode:
            self.mode_switches += 1
        self.mode = new_mode

        chosen = {}
        allocations = {}
        if self.mode == "LO":
            # HI workloads at Full, placed with smallest response time.
            for w in hi:
                full = [a for a in feasible[w.name]
                        if a[1] == ExecutionMode.FULL]
                for loc, mode in sorted(
                        full,
                        key=lambda a: estimate_latency(w, a[0], a[1], system)):
                    with _hi_budget(w, self.margin):
                        fits = can_allocate(w, loc, mode, system, allocations)
                        if fits:
                            allocate(w, loc, mode, allocations)
                    if fits:
                        chosen[w.name] = (loc, mode)
                        break
            lo_modes = ([ExecutionMode.FULL, ExecutionMode.REDUCED,
                         ExecutionMode.FALLBACK]
                        if self.elastic else [ExecutionMode.FULL])
        else:
            combo, allocations = self._hi_mode_selection(hi, system, feasible)
            for w, a in zip(hi, combo):
                if a is not None:
                    chosen[w.name] = a
            lo_modes = ([ExecutionMode.FULL, ExecutionMode.REDUCED,
                         ExecutionMode.FALLBACK]
                        if self.elastic else [])

        for w in lo:
            action = self._place_lo(w, system, feasible, allocations, lo_modes)
            if action is None:
                # LO workload cannot be admitted: dropped (suspended).
                action = self._suspend(w, system, feasible, allocations)
            if action is not None:
                allocate(w, action[0], action[1], allocations)
                chosen[w.name] = action

        decisions = []
        for w in system.workloads:
            action = chosen.get(w.name)
            if action is None:
                decisions.append({"workload": w.name, "location": None,
                                  "mode": None})
                continue
            update_workload_state(w, action[0], action[1])
            decisions.append({"workload": w.name, "location": action[0],
                              "mode": action[1]})
        return decisions
