"""
MDP-Migration baseline: adaptation of the distance-based MDP service-migration
policy of S. Wang et al., "Dynamic Service Migration in Mobile Edge Computing
Based on Markov Decision Process", IEEE/ACM ToN 27(3), 2019.

Original principles
-------------------
* The state is the distance between the mobile user and the edge server that
  hosts its service; the action is to keep the service or migrate it.
* The one-step cost is a transmission cost that grows with distance plus a
  migration cost when the service is moved.
* The policy minimises the discounted sum of future costs and is computed
  offline (modified policy iteration in the original paper).

Adaptation to this simulator (documented in the paper)
------------------------------------------------------
* The eVTOL route is known and deterministic (0 -> 10 km), so the MDP over
  distance becomes a finite-horizon discounted dynamic program over position,
  solved offline by backward induction with nominal network conditions
  (Normal-scenario latency and loss), discount GAMMA.
* States/actions are the execution locations {Edge_1, Edge_2, Cloud, Onboard}
  of each non-critical workload; the transmission cost is the latency cost
  C^lat (Eq. (16)), out-of-coverage edges have infinite cost, and the
  migration cost is C^mig (Eq. (15)).
* At run time the placement minimises  C^lat(observed) + C^mig + GAMMA * V(x_{t+1}).
* The original paper does not choose service modes or treat criticality, so
  the mode rule of the original-study baselines is used (highest feasible
  service mode per workload, workloads in list order; critical workloads
  are onboard-only through the shared feasibility layer).

Limitations: the value function uses nominal conditions (no model of the
stochastic link, loads or scenarios), as the original assumes a known,
stationary cost model.
"""

import copy

import config
from models.catalog import create_system
from models.workload import ExecutionMode, Location
from orchestrator.feasibility import get_feasible_actions, network_latency
from orchestrator.migration import raw_migration_time_ms
from orchestrator.resource_manager import can_allocate, allocate
from orchestrator.runtime import update_workload_state

GAMMA = 0.9
LOCS = [Location.ONBOARD, Location.EDGE_1, Location.EDGE_2, Location.CLOUD]
RANK = {ExecutionMode.FULL: 3, ExecutionMode.REDUCED: 2,
        ExecutionMode.FALLBACK: 1, ExecutionMode.SUSPENDED: 0}
INF = float("inf")


class MDPMigrationPolicy:
    name = "MDP-Migration"

    def __init__(self, gamma=GAMMA):
        self.gamma = gamma
        self._values = None

    def reset(self):
        self._values = None

    # ------------------------------------------------------------------
    def _offline_values(self, coverage):
        """V[name][t][loc]: discounted future cost from step t at loc."""
        nominal = create_system(coverage_radius_km=coverage)  # Normal targets
        n = config.NUM_STEPS
        values = {}
        for w in nominal.workloads:
            V = [{loc: 0.0 for loc in LOCS} for _ in range(n + 1)]
            for t in range(n - 1, -1, -1):
                nominal.evtol_position = min(t * config.EVTOL_SPEED_KM_PER_STEP,
                                             config.ROUTE_LENGTH_KM)
                for loc in LOCS:
                    stage = self._stage_cost(w, loc, nominal)
                    if stage == INF:
                        V[t][loc] = INF
                        continue
                    best_next = min(
                        (V[t + 1][nxt] + self._mig(w, loc, nxt, nominal))
                        for nxt in LOCS)
                    V[t][loc] = stage + self.gamma * best_next
            values[w.name] = V
        return values

    @staticmethod
    def _stage_cost(w, loc, system):
        if loc in (Location.EDGE_1, Location.EDGE_2) and system.coverage_radius_km:
            if not config.edge_in_coverage(loc.value, system.evtol_position,
                                           system.coverage_radius_km):
                return INF
        latency = w.compute_requirement + network_latency(loc, system)
        return config.LATENCY_COST_SCALE * latency / w.deadline

    @staticmethod
    def _mig(w, src, dst, system):
        t = raw_migration_time_ms(w, src, dst, system)
        return config.MIGRATION_COST_SCALE * t / max(w.deadline, 1.0)

    # ------------------------------------------------------------------
    def decide(self, system, ctx=None):
        if self._values is None:
            self._values = self._offline_values(system.coverage_radius_km)
        t = system.time
        allocations, decisions = {}, []
        for w in system.workloads:
            cands = [a for a in get_feasible_actions(w, system)
                     if can_allocate(w, a[0], a[1], system, allocations)]
            if not cands:
                decisions.append({"workload": w.name, "location": None,
                                  "mode": None})
                continue
            top = max(RANK[a[1]] for a in cands)
            cands = [a for a in cands if RANK[a[1]] == top]
            V = self._values[w.name]
            nxt = min(t + 1, len(V) - 1)
            prev = w.current_location if w.previous_location is not None else None

            def q(action):
                loc, mode = action
                k = config.MODE_SCALE[mode.value]
                cost = (config.LATENCY_COST_SCALE
                        * (w.compute_requirement * k + network_latency(loc, system))
                        / w.deadline) if mode != ExecutionMode.SUSPENDED else 0.0
                if prev is not None and prev != loc:
                    cost += self._mig(w, prev, loc, system)
                return cost + self.gamma * V[nxt][loc]

            loc, mode = min(cands, key=q)
            allocate(w, loc, mode, allocations)
            update_workload_state(w, loc, mode)
            decisions.append({"workload": w.name, "location": loc,
                              "mode": mode})
        return decisions
