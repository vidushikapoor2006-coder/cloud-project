"""
Receding-horizon dynamic-programming (RH-DP) comparator (Reviewer 2, comment 5).

At step t the policy plans over the horizon t, ..., t+H-1 and executes only the
first-stage decision (model-predictive / receding-horizon control).

Objective: a scalarised approximation to the proposed policy's two-level
utility/score objective over the horizon:
    maximise  sum_k [ BIG * sum_i U_i(k) + sum_i (S_i(k) - C^mig_i(k)) ]
The implementation uses BIG=1e6. At each stage, each non-critical workload's
candidate set is pruned to its top-M actions (plus its current-location action
and suspension/unserved option). Therefore this is a candidate-pruned RH-DP
reference, not an exact optimiser over the unrestricted action space. The
scalarisation is intended to preserve utility priority over the bounded score
term for the configured workloads and horizon; it is not a general proof of
lexicographic equivalence for arbitrary scales or horizons.

Coupling between stages: migration cost C^mig and the migration-aware
deadline constraint T_i + T_mig <= D_i.  Flight-critical workloads are
onboard-only and incur no migration, so their stage problems are independent;
they are solved at each stage with the proposed Phase 1 (only their resource
usage enters the DP).

Forecasts:
  * "persistence" (implementable): mission phases from the known flight plan
    (an emergency in progress is assumed to persist), eVTOL position from the
    known route, every other quantity equal to its current observed value.
  * "oracle" (NOT implementable; upper-bound reference): the true future
    observed states of the trace, including the unplanned emergency.

State-space restriction: per stage, each non-critical workload keeps its top-M
actions by (U, S), the best action at its current location, and suspension or
"unserved"; joint nodes are their resource-feasible products.
"""

import copy
from itertools import product

import numpy as np

import config
from models.mission import MissionPhase
from models.workload import Criticality, ExecutionMode, Location
from orchestrator.decision import (
    _select_critical_actions, _commit_decision, _append_infeasible,
)
from orchestrator.feasibility import get_feasible_actions, estimate_latency
from orchestrator.migration import raw_migration_time_ms
from orchestrator.resource_manager import can_allocate, allocate
from orchestrator.utility import calculate_score

BIG = 1e6
LOCS = [Location.ONBOARD, Location.EDGE_1, Location.EDGE_2, Location.CLOUD, None]
LOC_ID = {loc: i for i, loc in enumerate(LOCS)}


class LookaheadPolicy:

    def __init__(self, horizon=None, forecast="persistence", top_m=None):
        self.horizon = horizon or config.LOOKAHEAD_HORIZON
        self.forecast = forecast
        self.top_m = top_m or config.LOOKAHEAD_TOP_M
        tag = "-Oracle" if forecast == "oracle" else ""
        self.name = f"RH-DP{tag}"
        self.last_stats = {}

    def reset(self):
        pass

    # ------------------------------------------------------------------
    def _stage_systems(self, system, ctx):
        from simulation.environment import apply_observation
        trace = ctx["trace"]
        t = ctx["t"]
        stages = [system]
        for k in range(1, self.horizon):
            if t + k >= len(trace):
                break
            s = copy.deepcopy(system)
            future = trace[t + k]
            if self.forecast == "oracle":
                apply_observation(s, future, phase_attr="phase")
            else:
                s.time = t + k
                s.evtol_position = future.position
                if system.mission.phase != MissionPhase.EMERGENCY:
                    s.mission.phase = MissionPhase[future.planned_phase]
            stages.append(s)
        return stages

    def _stage_nodes(self, s, noncrit, stats):
        crit = [w for w in s.workloads
                if w.criticality == Criticality.VERY_HIGH]
        p1_stats = {"phase1_evaluated": 0, "phase1_feasible": 0}
        feasible = {w.name: get_feasible_actions(w, s, include_migration=False)
                    for w in s.workloads}
        best = _select_critical_actions(crit, s, feasible, p1_stats)
        stats["phase1_evaluated"] += p1_stats["phase1_evaluated"]
        crit_alloc = {k: dict(v) for k, v in best["allocations"].items()}

        per_workload = []
        for w in noncrit:
            cands = []
            for loc, mode in feasible[w.name]:
                if not can_allocate(w, loc, mode, s, crit_alloc):
                    continue
                r = calculate_score(w, loc, mode, s)
                cands.append(((r["utility"], r["score"]), loc, mode,
                              estimate_latency(w, loc, mode, s)))
            cands.sort(key=lambda c: c[0], reverse=True)
            keep = cands[: self.top_m]
            stay = [c for c in cands if c[1] == w.current_location]
            if stay and stay[0] not in keep:
                keep.append(stay[0])
            # Fallback option: suspension (as the proposed policy would
            # choose when nothing else fits), else "unserved".
            susp = [c for c in cands if c[2] == ExecutionMode.SUSPENDED]
            if susp:
                if susp[0] not in keep:
                    keep.append(susp[0])
            else:
                keep.append(((0.0, 0.0), None, None, 0.0))
            per_workload.append(keep)

        nodes = []
        for combo in product(*per_workload):
            stats["nodes_evaluated"] += 1
            alloc = {k: dict(v) for k, v in crit_alloc.items()}
            ok = True
            for w, c in zip(noncrit, combo):
                if c[1] is None:
                    continue
                if not can_allocate(w, c[1], c[2], s, alloc):
                    ok = False
                    break
                allocate(w, c[1], c[2], alloc)
            if not ok:
                continue
            value = (sum(c[0][0] for c in combo) * BIG
                     + sum(c[0][1] for c in combo))
            nodes.append((value, combo))
        stats["nodes_feasible"] += len(nodes)
        return best, nodes

    def _mig_matrix(self, w, s, latency_by_loc):
        """5x5 matrices (from, to) of C_mig and transition feasibility."""
        cost = np.zeros((5, 5))
        ok = np.ones((5, 5), dtype=bool)
        for i, src in enumerate(LOCS):
            for j, dst in enumerate(LOCS):
                if src is None or dst is None or src == dst:
                    continue
                t_mig = raw_migration_time_ms(w, src, dst, s)
                cost[i, j] = (t_mig / max(w.deadline, 1.0)) * config.MIGRATION_COST_SCALE
                if (config.MIGRATION_DOWNTIME_IN_DEADLINE
                        and latency_by_loc.get(dst, 0.0) + t_mig > w.deadline):
                    ok[i, j] = False
        return cost, ok

    def _trans_matrix(self, from_ids, nodes, noncrit, s):
        """Vectorised transition values (-sum C_mig, -inf if infeasible)."""
        n_from = from_ids.shape[0]
        total = np.zeros((n_from, len(nodes)))
        for idx, w in enumerate(noncrit):
            lat = {}
            for _, combo in nodes:
                c = combo[idx]
                if c[1] is not None:
                    lat[c[1]] = max(lat.get(c[1], 0.0), c[3])
            cost, ok = self._mig_matrix(w, s, lat)
            to_ids = np.array([LOC_ID[combo[idx][1]] for _, combo in nodes])
            sub_cost = cost[from_ids[:, idx][:, None], to_ids[None, :]]
            sub_ok = ok[from_ids[:, idx][:, None], to_ids[None, :]]
            # an unserved target keeps the state where it was
            unserved = (to_ids == LOC_ID[None])
            sub_cost[:, unserved] = 0.0
            sub_ok[:, unserved] = True
            total -= sub_cost
            total[~sub_ok] = -np.inf
        return total

    @staticmethod
    def _locs_after(from_ids, nodes):
        """Location ids after moving to each node (unserved keeps origin)."""
        to = np.array([[LOC_ID[c[1]] for c in combo] for _, combo in nodes])
        return to

    # ------------------------------------------------------------------
    def decide(self, system, ctx):
        stats = {"phase1_evaluated": 0, "nodes_evaluated": 0,
                 "nodes_feasible": 0, "transitions": 0}
        noncrit = [w for w in system.workloads
                   if w.criticality != Criticality.VERY_HIGH]
        stages = self._stage_systems(system, ctx)
        stage_data = []
        for s in stages:
            nc = [x for x in s.workloads if x.criticality != Criticality.VERY_HIGH]
            stage_data.append(self._stage_nodes(s, nc, stats))

        # Initial placement (no previous location) is not a migration.
        current = np.array([[
            LOC_ID[w.current_location if w.previous_location is not None else None]
            for w in noncrit]])

        best0, nodes0 = stage_data[0]
        values = (np.array([v for v, _ in nodes0])
                  + self._trans_matrix(current, nodes0, noncrit, stages[0])[0])
        stats["transitions"] += len(nodes0)
        origin = np.arange(len(nodes0))
        loc_state = self._locs_after(current, nodes0)
        loc_state = np.where(loc_state == LOC_ID[None], current, loc_state)

        for k in range(1, len(stages)):
            _, nodes_k = stage_data[k]
            if not nodes_k or not np.isfinite(values).any():
                break
            s = stages[k]
            nc_k = [x for x in s.workloads if x.criticality != Criticality.VERY_HIGH]
            trans = self._trans_matrix(loc_state, nodes_k, nc_k, s)
            stats["transitions"] += trans.size
            node_vals = np.array([v for v, _ in nodes_k])
            total = values[:, None] + trans + node_vals[None, :]
            best_prev = np.argmax(total, axis=0)
            new_values = total[best_prev, np.arange(len(nodes_k))]
            new_origin = origin[best_prev]
            to = self._locs_after(None, nodes_k)
            new_loc = np.where(to == LOC_ID[None], loc_state[best_prev], to)
            values, origin, loc_state = new_values, new_origin, new_loc

        decisions = []
        allocations = {}
        # Critical workloads: stage-0 Phase-1 solution.
        crit = [w for w in system.workloads
                if w.criticality == Criticality.VERY_HIGH]
        for w, a, r in zip(crit, best0["combination"], best0["results"]):
            if a is None:
                _append_infeasible(w, decisions)
            else:
                _commit_decision(w, a[0], a[1], r, allocations, decisions)

        if np.isfinite(values).any():
            chosen = nodes0[origin[int(np.argmax(values))]][1]
        else:
            chosen = tuple(((0, 0), None, None, 0.0) for _ in noncrit)
        for w, c in zip(noncrit, chosen):
            if c[1] is None:
                _append_infeasible(w, decisions)
                continue
            r = calculate_score(w, c[1], c[2], system)
            _commit_decision(w, c[1], c[2], r, allocations, decisions)
        self.last_stats = stats
        return decisions
