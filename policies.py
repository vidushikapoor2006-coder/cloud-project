"""
Uniform policy interface used by the experiment engine.

Every policy exposes  reset()  and  decide(system, ctx) -> list of decisions,
where each decision is {"workload", "location", "mode"} (location None means
"no feasible action").  All policies use the SAME feasibility layer
(orchestrator/feasibility.py), including the onboard-only safety restriction,
and are run on the SAME environment traces and seeds.
"""

from models.workload import Location, ExecutionMode
from orchestrator.runtime import update_workload_state
from orchestrator.feasibility import is_action_feasible
from orchestrator.resource_manager import can_allocate, allocate
from orchestrator import decision as proposed
from orchestrator import decision_v1 as proposed_v1
from orchestrator.lookahead import LookaheadPolicy
from baselines.static_baseline import STATIC_ACTIONS
from baselines.qos_based import select_qos_based_action
from baselines.resource_aware import select_resource_aware_action
from baselines.utility_based import select_utility_based_action
from baselines.mixed_criticality import MixedCriticalityPolicy
from baselines.mdp_migration import MDPMigrationPolicy


class StaticPolicy:
    """Fixed initial allocation, never adapted (original baseline)."""
    name = "Static"

    def reset(self):
        pass

    def decide(self, system, ctx=None):
        decisions = []
        allocations = {}
        for w in system.workloads:
            location, mode = STATIC_ACTIONS[w.name]
            # Static always issues its fixed assignment.  Whether that
            # assignment is feasible is recorded (cumulative check, Eq. (12))
            # and its actual outcome is decided by the execution model.
            planned_ok = (
                is_action_feasible(w, location, mode, system)
                and can_allocate(w, location, mode, system, allocations)
            )
            if planned_ok:
                allocate(w, location, mode, allocations)
            update_workload_state(w, location, mode)
            decisions.append({"workload": w.name, "location": location,
                              "mode": mode, "planned_feasible": planned_ok})
        return decisions


class GreedyBaseline:
    """Per-workload greedy baselines of the original submission."""

    def __init__(self, name, selector):
        self.name = name
        self.selector = selector

    def reset(self):
        pass

    def decide(self, system, ctx=None):
        allocations = {}
        decisions = []
        for w in system.workloads:
            action = self.selector(w, system, allocations)
            if action is None:
                decisions.append({"workload": w.name, "location": None,
                                  "mode": None})
                continue
            update_workload_state(w, action[0], action[1])
            decisions.append({"workload": w.name, "location": action[0],
                              "mode": action[1]})
        return decisions


class ProposedPolicy:

    def __init__(self, version="revised", margin=None, name=None,
                 ablation=None):
        self.version = version
        self.margin = margin
        self.ablation = ablation
        self.name = name or ("Proposed" if version == "revised"
                             else "Proposed-v1")
        self.last_stats = {}

    def reset(self):
        pass

    def decide(self, system, ctx=None):
        if self.version == "revised":
            stats = {}
            decisions = proposed.select_actions_globally(
                system, stats, margin=self.margin, ablation=self.ablation)
            self.last_stats = stats
            return decisions
        return proposed_v1.select_actions_globally(system)


def make_policies(include=None):
    policies = [
        StaticPolicy(),
        GreedyBaseline("QoS-Based", select_qos_based_action),
        GreedyBaseline("Resource-Aware", select_resource_aware_action),
        GreedyBaseline("Utility-Based", select_utility_based_action),
        MixedCriticalityPolicy(elastic=False),
        MixedCriticalityPolicy(elastic=True),
        MDPMigrationPolicy(),
        ProposedPolicy("v1"),
        ProposedPolicy("revised"),
        LookaheadPolicy(forecast="persistence"),
        LookaheadPolicy(forecast="oracle"),
    ]
    if include is not None:
        policies = [p for p in policies if p.name in include]
    return policies


POLICY_ORDER = [
    "Static", "QoS-Based", "Resource-Aware", "Utility-Based",
    "AMC-Adapted", "Elastic-MC", "MDP-Migration", "Proposed-v1", "Proposed",
    "RH-DP", "RH-DP-Oracle",
]


ABLATIONS = {
    "Abl-FixedOrder": {"phase_priority": False},
    "Abl-PhaseBlind": {"phase_aware": False, "phase_priority": False},
    "Abl-NoJointAdmission": {"joint_admission": False},
    "Abl-NoMigCost": {"migration_cost": False},
    "Abl-NoDegradation": {"degradation": False},
}


def make_ablation_policies():
    return [ProposedPolicy("revised")] + [
        ProposedPolicy("revised", name=n, ablation=a)
        for n, a in ABLATIONS.items()]
