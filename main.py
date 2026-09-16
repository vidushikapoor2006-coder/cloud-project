from execution.aws_iot_client import connect, publish_mission, disconnect
from models.workload import (
    Workload,
    Criticality,
    Location,
    ExecutionMode,
    WorkloadState
)

from models.resource import ResourceState

from models.mission import (
    MissionState,
    MissionPhase,
    NetworkState
)

from models.state import SystemState

from orchestrator.feasibility import get_feasible_actions

from orchestrator.utility import calculate_score

from orchestrator.decision import select_actions_globally

from simulation.scenarios import (
    normal_conditions,
    network_degradation,
    edge_overload,
    cloud_failure,
    resource_pressure,
    emergency_mission,
    severe_degradation,
    recovery
)

from orchestrator.history import (
    AdaptationEvent,
    classify_adaptation
)

from metrics import calculate_scenario_metrics

from simulation.timeline import create_timeline

from simulation.records import TimeStepRecord

from baselines.static_baseline import run_static_baseline

from baselines.static_runner import run_static_timeline

from baselines.resource_runner import (
    run_resource_aware_timeline
)


# =========================================================
# SCENARIO FUNCTIONS
# =========================================================

SCENARIO_FUNCTIONS = {
    "Normal": normal_conditions,
    "Network Degradation": network_degradation,
    "Edge Overload": edge_overload,
    "Cloud Failure": cloud_failure,
    "Resource Pressure": resource_pressure,
    "Emergency Mission": emergency_mission,
    "Severe Degradation": severe_degradation,
    "Recovery": recovery
}


# =========================================================
# WORKLOADS
# =========================================================

workloads = [

    Workload(
        name="Obstacle Detection",
        criticality=Criticality.VERY_HIGH,
        deadline=50,
        compute_requirement=30,
        memory_requirement=20,
        energy_requirement=15,
        network_requirement=10
    ),

    Workload(
        name="Navigation",
        criticality=Criticality.VERY_HIGH,
        deadline=50,
        compute_requirement=35,
        memory_requirement=25,
        energy_requirement=15,
        network_requirement=10
    ),

    Workload(
        name="Weather Analysis",
        criticality=Criticality.HIGH,
        deadline=200,
        compute_requirement=20,
        memory_requirement=15,
        energy_requirement=8,
        network_requirement=20
    ),

    Workload(
        name="Video Analytics",
        criticality=Criticality.MEDIUM,
        deadline=150,
        compute_requirement=30,
        memory_requirement=20,
        energy_requirement=10,
        network_requirement=30
    ),

    Workload(
        name="Flight Logging",
        criticality=Criticality.LOW,
        deadline=500,
        compute_requirement=10,
        memory_requirement=10,
        energy_requirement=3,
        network_requirement=5
    )
]


# =========================================================
# RESOURCES
# =========================================================

onboard = ResourceState(
    name="Onboard",
    cpu_capacity=100,
    cpu_used=20,
    memory_capacity=100,
    memory_used=20,
    energy_available=100
)


edge_1 = ResourceState(
    name="Edge 1",
    cpu_capacity=100,
    cpu_used=30,
    memory_capacity=100,
    memory_used=25,
    energy_available=100
)


edge_2 = ResourceState(
    name="Edge 2",
    cpu_capacity=100,
    cpu_used=40,
    memory_capacity=100,
    memory_used=30,
    energy_available=100
)


cloud = ResourceState(
    name="AWS Cloud",
    cpu_capacity=200,
    cpu_used=50,
    memory_capacity=200,
    memory_used=40,
    energy_available=100
)


# =========================================================
# MISSION + NETWORK
# =========================================================

mission = MissionState(
    phase=MissionPhase.CRUISE
)


network = NetworkState(
    latency=50,
    bandwidth=100,
    packet_loss=1
)


# =========================================================
# SYSTEM STATE
# =========================================================

system = SystemState(
    mission=mission,
    onboard=onboard,
    edge_1=edge_1,
    edge_2=edge_2,
    cloud=cloud,
    network=network,
    workloads=workloads
)


# =========================================================
# BASIC SYSTEM INFORMATION
# =========================================================

print("Mission Phase:", system.mission.phase.value)


print("\nWorkloads:")

for workload in system.workloads:

    print(
        workload.name,
        "| Criticality:",
        workload.criticality.name,
        "| Deadline:",
        workload.deadline
    )


print("\nResources:")

for resource in [
    system.onboard,
    system.edge_1,
    system.edge_2,
    system.cloud
]:

    print(
        resource.name,
        "| CPU Available:",
        resource.cpu_available,
        "| Memory Available:",
        resource.memory_available
    )


# =========================================================
# FEASIBLE ACTIONS
# =========================================================

print("\nFeasible Actions:")

for workload in system.workloads:

    actions = get_feasible_actions(
        workload,
        system
    )

    print(f"\n{workload.name}:")

    for location, mode in actions:

        print(
            " ",
            location.value,
            "+",
            mode.value
        )


# =========================================================
# ACTION SCORES
# =========================================================

print("\n\nAction Scores:")

for workload in system.workloads:

    actions = get_feasible_actions(
        workload,
        system
    )

    print(f"\n{workload.name}:")

    for location, mode in actions:

        result = calculate_score(
            workload,
            location,
            mode,
            system
        )

        print(
            f"  {location.value} + {mode.value}"
            f" | Utility: {result['utility']:.2f}"
            f" | Latency Cost: {result['latency_cost']:.2f}"
            f" | Energy Cost: {result['energy_cost']:.2f}"
            f" | Resource Cost: {result['resource_cost']:.2f}"
            f" | Score: {result['score']:.2f}"
        )


# =========================================================
# GLOBAL ORCHESTRATION SCENARIOS
# =========================================================

print("\n\n===== GLOBAL ORCHESTRATION SCENARIOS =====")

adaptation_history = []

scenario_metrics = []


scenarios = [
    ("Normal", normal_conditions),
    ("Network Degradation", network_degradation),
    ("Edge Overload", edge_overload),
    ("Cloud Failure", cloud_failure),
    ("Resource Pressure", resource_pressure),
    ("Emergency Mission", emergency_mission),
    ("Severe Degradation", severe_degradation),
    ("Recovery", recovery)
]


for scenario_name, scenario_function in scenarios:

    scenario_function(system)

    print(f"\n--- {scenario_name} ---")

    decisions = select_actions_globally(system)

    metrics = calculate_scenario_metrics(
        scenario_name,
        decisions,
        system
    )

    scenario_metrics.append(metrics)

    for decision in decisions:

        if decision["location"] is None:

            print(
                f"{decision['workload']}: "
                f"No feasible allocation"
            )

            continue

        workload = next(
            w for w in system.workloads
            if w.name == decision["workload"]
        )

        if decision["adapted"]:

            adaptation_type = classify_adaptation(
                workload.previous_location.value,
                workload.previous_mode.value,
                workload.current_location.value,
                workload.current_mode.value
            )

            event = AdaptationEvent(
                workload=workload.name,
                previous_location=workload.previous_location.value,
                previous_mode=workload.previous_mode.value,
                new_location=workload.current_location.value,
                new_mode=workload.current_mode.value,
                adaptation_type=adaptation_type,
                scenario=scenario_name
            )

            adaptation_history.append(event)

            print(
                f"{workload.name}: "
                f"{workload.current_location.value} + "
                f"{workload.current_mode.value}"
                f" | Score: "
                f"{decision['score']:.2f}"
                f" | Adapted: True"
                f" | Type: {adaptation_type}"
            )

        else:

            print(
                f"{workload.name}: "
                f"{workload.current_location.value} + "
                f"{workload.current_mode.value}"
                f" | Score: "
                f"{decision['score']:.2f}"
                f" | Adapted: False"
            )


# =========================================================
# SCENARIO METRICS
# =========================================================

print("\n\n===== SCENARIO METRICS =====")

for metrics in scenario_metrics:

    print(
        f"\n{metrics.scenario}"
    )

    print(
        f"  Mission Utility: "
        f"{metrics.total_utility:.2f}"
    )

    print(
        f"  Workloads Completed: "
        f"{metrics.workloads_completed}"
    )

    print(
        f"  Workloads Infeasible: "
        f"{metrics.workloads_infeasible}"
    )

    print(
        f"  Critical Workloads Successful: "
        f"{metrics.critical_workloads_successful}/"
        f"{metrics.critical_workloads_total}"
    )

    print(
        f"  Adaptations: "
        f"{metrics.adaptations}"
    )

    print(
        f"  Migrations: "
        f"{metrics.migrations}"
    )

    print(
        f"  Degradations: "
        f"{metrics.degradations}"
    )

    print(
        f"  Fallbacks: "
        f"{metrics.fallbacks}"
    )

    print(
        f"  Suspensions: "
        f"{metrics.suspensions}"
    )


# =========================================================
# ADAPTATION HISTORY
# =========================================================

print("\n\n===== ADAPTATION HISTORY =====")

for event in adaptation_history:

    print(
        f"{event.scenario} | "
        f"{event.workload} | "
        f"{event.previous_location} + "
        f"{event.previous_mode}"
        f" -> "
        f"{event.new_location} + "
        f"{event.new_mode}"
        f" | {event.adaptation_type}"
    )


# =========================================================
# SIMULATION TIMELINE
# =========================================================

print("\n\n===== SIMULATION TIMELINE =====")

timeline = create_timeline()

for step in timeline:

    print(
        f"t={step.time:02d} | "
        f"{step.scenario}"
    )
# =========================================================
# AWS IoT CONNECTION
# =========================================================

connect()

# =========================================================
# PROPOSED POLICY — TIME-BASED ORCHESTRATION
# =========================================================

print("\n\n===== TIME-BASED ORCHESTRATION =====")


# Reset workload runtime state

for workload in system.workloads:

    workload.current_location = Location.ONBOARD
    workload.current_mode = ExecutionMode.FULL
    workload.previous_location = None
    workload.previous_mode = None
    workload.state = WorkloadState.RUNNING


timeline = create_timeline()
time_series = []


for step in timeline:

    # Update eVTOL position for mobility-aware edge selection
    system.evtol_position = min(step.time * 0.125, 10.0)
    print(
    f"t={step.time:02d} | "
    f"eVTOL Position={system.evtol_position:.2f} km"
    )

    scenario_function = SCENARIO_FUNCTIONS[
        step.scenario
    ]

    scenario_function(system)

    decisions = select_actions_globally(system)

    # Publish the initial state and every actual adaptation to AWS IoT.
    # This avoids sending all 400 possible workload decisions.
    for decision in decisions:

        if decision["location"] is None:
            continue

        if step.time == 0 or decision["adapted"]:

            publish_mission(
                mission_id=(
                    f"mission-{step.time:03d}-"
                    f"{decision['workload'].replace(' ', '-')}"
                ),
                workload=decision["workload"],
                mode=decision["mode"].value,
                mission_phase=system.mission.phase.value,
                location=decision["location"].value
            )

    metrics = calculate_scenario_metrics(
        step.scenario,
        decisions,
        system
    )

    time_series.append(
        TimeStepRecord(
            time=step.time,
            scenario=step.scenario,
            mission_utility=metrics.total_utility,
            workloads_completed=metrics.workloads_completed,
            workloads_infeasible=metrics.workloads_infeasible,
            adaptations=metrics.adaptations,
            migrations=metrics.migrations,
            degradations=metrics.degradations,
            fallbacks=metrics.fallbacks,
            suspensions=metrics.suspensions,
            decisions=decisions
        )
    )

    print(
        f"t={step.time:02d} | "
        f"{step.scenario:<22} | "
        f"Utility: {metrics.total_utility:6.2f} | "
        f"Completed: {metrics.workloads_completed} | "
        f"Infeasible: {metrics.workloads_infeasible} | "
        f"Adaptations: {metrics.adaptations}"
    )


disconnect()


# PROPOSED POLICY — DECISION DETAILS
# =========================================================

print("\n\n===== PROPOSED POLICY DECISION DETAILS =====")


important_times = {
    10,
    20,
    30,
    40,
    50
}


for record in time_series:

    if record.time not in important_times:
        continue

    print(
        f"\nt={record.time} | "
        f"{record.scenario}"
    )

    for decision in record.decisions:

        if decision["location"] is None:

            print(
                f"  {decision['workload']}: "
                f"INFEASIBLE"
            )

            continue

        print(
            f"  {decision['workload']}: "
            f"{decision['location'].value} + "
            f"{decision['mode'].value}"
            f" | Utility="
            f"{decision['details']['utility']:.2f}"
            f" | Score="
            f"{decision['score']:.2f}"
        )


# =========================================================
# ADAPTATION TRANSITIONS
# =========================================================

print("\n\n===== ADAPTATION TRANSITIONS =====")

previous_actions = {
    workload.name: (
        Location.ONBOARD.value,
        ExecutionMode.FULL.value
    )
    for workload in system.workloads
}


for step in timeline:

    # Update eVTOL position for mobility-aware edge selection.
    system.evtol_position = min(step.time * 0.125, 10.0)

    scenario_function = SCENARIO_FUNCTIONS[
        step.scenario
    ]

    scenario_function(system)

    decisions = select_actions_globally(system)

    for decision in decisions:

        if decision["location"] is None:
            continue

        workload_name = decision["workload"]

        new_action = (
            decision["location"].value,
            decision["mode"].value
        )

        old_action = previous_actions[
            workload_name
        ]

        if old_action != new_action:

            print(
                f"t={step.time:02d} | "
                f"{step.scenario:<22} | "
                f"{workload_name:<22} | "
                f"{old_action[0]} + {old_action[1]} "
                f"-> "
                f"{new_action[0]} + {new_action[1]} | "
                f"{decision['adaptation_type']}"
            )

        previous_actions[workload_name] = new_action


# =========================================================
# STATIC BASELINE
# =========================================================

print("\n\n===== STATIC BASELINE TEST =====")

static_decisions = run_static_baseline(system)


for decision in static_decisions:

    print(
        f"{decision['workload']}: "
        f"{decision['location'].value} + "
        f"{decision['mode'].value}"
    )


print("\n\n===== STATIC BASELINE TIMELINE =====")

static_records = run_static_timeline(system)


for record in static_records:

    print(
        f"t={record.time:02d} | "
        f"{record.scenario:<22} | "
        f"Utility: {record.mission_utility:6.2f} | "
        f"Completed: {record.workloads_completed} | "
        f"Infeasible: {record.workloads_infeasible}"
    )


# =========================================================
# RESOURCE-AWARE BASELINE
# =========================================================

print("\n\n===== RESOURCE-AWARE BASELINE TIMELINE =====")

resource_records = run_resource_aware_timeline(system)


for record in resource_records:

    print(
        f"t={record.time:02d} | "
        f"{record.scenario:<22} | "
        f"Utility: {record.mission_utility:6.2f} | "
        f"Completed: {record.workloads_completed} | "
        f"Infeasible: {record.workloads_infeasible}"
    )