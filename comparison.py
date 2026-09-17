from models.workload import Workload, Criticality
from models.resource import ResourceState
from models.mission import MissionState, MissionPhase, NetworkState
from models.state import SystemState

from simulation.timeline import create_timeline

from simulation.scenarios import (
    normal_conditions,
    network_degradation,
    edge_overload,
    cloud_failure,
    resource_pressure,
    emergency_mission,
    severe_degradation,
    recovery,
)

from orchestrator.decision import select_actions_globally

from baselines.resource_aware import (
    select_resource_aware_action
)

from baselines.qos_based import (
    select_qos_based_action
)

from baselines.utility_based import (
    select_utility_based_action
)

from baselines.static_baseline import STATIC_ACTIONS

from orchestrator.feasibility import (
    has_enough_resources,
    network_is_feasible,
    meets_deadline,
)

from orchestrator.utility import calculate_utility

from simulation.records import TimeStepRecord

from orchestrator.runtime import update_workload_state

from orchestrator.history import classify_adaptation


# ============================================================
# SCENARIOS
# ============================================================

SCENARIO_FUNCTIONS = {
    "Normal": normal_conditions,
    "Network Degradation": network_degradation,
    "Edge Overload": edge_overload,
    "Cloud Failure": cloud_failure,
    "Resource Pressure": resource_pressure,
    "Emergency Mission": emergency_mission,
    "Severe Degradation": severe_degradation,
    "Recovery": recovery,
}


# ============================================================
# SYSTEM CREATION
# ============================================================

def create_system():

    workloads = [

        Workload(
            name="Obstacle Detection",
            criticality=Criticality.VERY_HIGH,
            deadline=50,
            compute_requirement=30,
            memory_requirement=20,
            energy_requirement=15,
            network_requirement=10,
        ),

        Workload(
            name="Navigation",
            criticality=Criticality.VERY_HIGH,
            deadline=50,
            compute_requirement=35,
            memory_requirement=25,
            energy_requirement=15,
            network_requirement=10,
        ),

        Workload(
            name="Weather Analysis",
            criticality=Criticality.HIGH,
            deadline=200,
            compute_requirement=20,
            memory_requirement=15,
            energy_requirement=8,
            network_requirement=20,
        ),

        Workload(
            name="Video Analytics",
            criticality=Criticality.MEDIUM,
            deadline=150,
            compute_requirement=30,
            memory_requirement=20,
            energy_requirement=10,
            network_requirement=30,
        ),

        Workload(
            name="Flight Logging",
            criticality=Criticality.LOW,
            deadline=500,
            compute_requirement=10,
            memory_requirement=10,
            energy_requirement=3,
            network_requirement=5,
        ),
    ]


    onboard = ResourceState(
        name="Onboard",
        cpu_capacity=100,
        cpu_used=20,
        memory_capacity=100,
        memory_used=20,
        energy_available=100,
    )


    edge_1 = ResourceState(
        name="Edge_1",
        cpu_capacity=100,
        cpu_used=30,
        memory_capacity=100,
        memory_used=25,
        energy_available=100,
    )


    edge_2 = ResourceState(
        name="Edge_2",
        cpu_capacity=100,
        cpu_used=40,
        memory_capacity=100,
        memory_used=30,
        energy_available=100,
    )


    cloud = ResourceState(
        name="AWS_Cloud",
        cpu_capacity=200,
        cpu_used=50,
        memory_capacity=200,
        memory_used=40,
        energy_available=100,
    )


    mission = MissionState(
        phase=MissionPhase.CRUISE,
        emergency=False,
    )


    network = NetworkState(
        latency=50,
        bandwidth=100,
        packet_loss=1,
        connected=True,
    )


    return SystemState(
        mission=mission,
        onboard=onboard,
        edge_1=edge_1,
        edge_2=edge_2,
        cloud=cloud,
        network=network,
        workloads=workloads,
    )


# ============================================================
# ADAPTATION COUNTER
# ============================================================

def count_adaptation(
    previous_location,
    previous_mode,
    location,
    mode
):

    adaptation_type = classify_adaptation(
        previous_location.value,
        previous_mode.value,
        location.value,
        mode.value
    )

    adaptations = 0
    migrations = 0
    degradations = 0
    fallbacks = 0
    suspensions = 0

    if adaptation_type != "No Change":
        adaptations += 1

    if "Migration" in adaptation_type:
        migrations += 1

    if "Degradation" in adaptation_type:
        degradations += 1

    if "Fallback" in adaptation_type:
        fallbacks += 1

    if "Suspension" in adaptation_type:
        suspensions += 1

    return (
        adaptation_type,
        adaptations,
        migrations,
        degradations,
        fallbacks,
        suspensions,
    )


# ============================================================
# STATIC BASELINE
# ============================================================

def run_static_step(system):

    total_utility = 0

    workloads_completed = 0
    workloads_infeasible = 0

    decisions = []


    for workload in system.workloads:

        location, mode = STATIC_ACTIONS[
            workload.name
        ]


        resource_ok = has_enough_resources(
            workload,
            location,
            mode,
            system
        )


        network_ok = network_is_feasible(
            workload,
            location,
            system
        )


        deadline_ok = meets_deadline(
            workload,
            location,
            mode,
            system
        )


        if (
            resource_ok
            and network_ok
            and deadline_ok
        ):

            utility = calculate_utility(
                workload,
                mode,
                system.mission.phase
            )

            total_utility += utility

            workloads_completed += 1

        else:

            workloads_infeasible += 1


        decisions.append({
            "workload": workload.name,
            "location": location.value,
            "mode": mode.value,
            "adaptation": "No Change",
        })


    return {
        "mission_utility": total_utility,
        "workloads_completed": workloads_completed,
        "workloads_infeasible": workloads_infeasible,
        "adaptations": 0,
        "migrations": 0,
        "degradations": 0,
        "fallbacks": 0,
        "suspensions": 0,
        "decisions": decisions,
    }


# ============================================================
# GENERIC ADAPTIVE BASELINE RUNNER
# ============================================================

def run_adaptive_baseline_step(
    system,
    selector
):

    allocations = {}

    total_utility = 0

    workloads_completed = 0
    workloads_infeasible = 0

    adaptations = 0
    migrations = 0
    degradations = 0
    fallbacks = 0
    suspensions = 0

    decisions = []


    for workload in system.workloads:

        previous_location = workload.current_location
        previous_mode = workload.current_mode


        result = selector(
            workload,
            system,
            allocations
        )


        if result is None:

            workloads_infeasible += 1

            decisions.append({
                "workload": workload.name,
                "location": None,
                "mode": None,
                "adaptation": "Infeasible",
            })

            continue


        location, mode = result


        workloads_completed += 1


        utility = calculate_utility(
            workload,
            mode,
            system.mission.phase
        )


        total_utility += utility


        update_workload_state(
            workload,
            location,
            mode
        )


        (
            adaptation_type,
            a,
            m,
            d,
            f,
            s,
        ) = count_adaptation(
            previous_location,
            previous_mode,
            location,
            mode
        )


        adaptations += a
        migrations += m
        degradations += d
        fallbacks += f
        suspensions += s


        decisions.append({
            "workload": workload.name,
            "location": location.value,
            "mode": mode.value,
            "adaptation": adaptation_type,
        })


    return {
        "mission_utility": total_utility,
        "workloads_completed": workloads_completed,
        "workloads_infeasible": workloads_infeasible,
        "adaptations": adaptations,
        "migrations": migrations,
        "degradations": degradations,
        "fallbacks": fallbacks,
        "suspensions": suspensions,
        "decisions": decisions,
    }


# ============================================================
# QOS-BASED BASELINE
# ============================================================

def run_qos_based_step(system):

    return run_adaptive_baseline_step(
        system,
        select_qos_based_action
    )


# ============================================================
# RESOURCE-AWARE BASELINE
# ============================================================

def run_resource_aware_step(system):

    return run_adaptive_baseline_step(
        system,
        select_resource_aware_action
    )


# ============================================================
# UTILITY-BASED BASELINE
# ============================================================

def run_utility_based_step(system):

    return run_adaptive_baseline_step(
        system,
        select_utility_based_action
    )


# ============================================================
# PROPOSED POLICY
# ============================================================

def run_proposed_step(system):

    decisions = select_actions_globally(
        system
    )


    total_utility = 0

    workloads_completed = 0
    workloads_infeasible = 0

    adaptations = 0
    migrations = 0
    degradations = 0
    fallbacks = 0
    suspensions = 0


    for decision in decisions:

        workload_name = decision[
            "workload"
        ]


        workload = next(
            (
                w
                for w in system.workloads
                if w.name == workload_name
            ),
            None
        )


        if workload is None:
            continue


        if (
            decision["location"] is None
            or decision["mode"] is None
        ):

            workloads_infeasible += 1

            continue


        workloads_completed += 1


        location = decision[
            "location"
        ]

        mode = decision[
            "mode"
        ]


        utility = calculate_utility(
            workload,
            mode,
            system.mission.phase
        )


        total_utility += utility


        if decision.get(
            "adapted",
            False
        ):

            adaptations += 1


        adaptation_type = decision.get(
            "adaptation_type",
            "No Change"
        )


        if "Migration" in adaptation_type:
            migrations += 1

        if "Degradation" in adaptation_type:
            degradations += 1

        if "Fallback" in adaptation_type:
            fallbacks += 1

        if "Suspension" in adaptation_type:
            suspensions += 1


    return {
        "mission_utility": total_utility,
        "workloads_completed": workloads_completed,
        "workloads_infeasible": workloads_infeasible,
        "adaptations": adaptations,
        "migrations": migrations,
        "degradations": degradations,
        "fallbacks": fallbacks,
        "suspensions": suspensions,
        "decisions": decisions,
    }


# ============================================================
# RUN POLICY
# ============================================================

def run_policy(
    policy_name,
    timeline
):

    system = create_system()

    records = []


    for step in timeline:

        # Update eVTOL position for mobility-aware edge latency.
        system.evtol_position = min(step.time * 0.125, 10.0)

        scenario_function = (
            SCENARIO_FUNCTIONS[
                step.scenario
            ]
        )


        scenario_function(
            system
        )


        if policy_name == "Static":

            result = run_static_step(
                system
            )


        elif policy_name == "QoS-Based":

            result = run_qos_based_step(
                system
            )


        elif policy_name == "Resource-Aware":

            result = run_resource_aware_step(
                system
            )


        elif policy_name == "Utility-Based":

            result = run_utility_based_step(
                system
            )


        elif policy_name == "Proposed":

            result = run_proposed_step(
                system
            )


        else:

            raise ValueError(
                f"Unknown policy: {policy_name}"
            )


        record = TimeStepRecord(
            time=step.time,
            scenario=step.scenario,
            mission_utility=result[
                "mission_utility"
            ],
            workloads_completed=result[
                "workloads_completed"
            ],
            workloads_infeasible=result[
                "workloads_infeasible"
            ],
            adaptations=result[
                "adaptations"
            ],
            migrations=result[
                "migrations"
            ],
            degradations=result[
                "degradations"
            ],
            fallbacks=result[
                "fallbacks"
            ],
            suspensions=result[
                "suspensions"
            ],
            decisions=result[
                "decisions"
            ],
        )


        records.append(
            record
        )


    return records


# ============================================================
# AGGREGATE RESULTS
# ============================================================

def aggregate_results(records):

    return {

        "utility": sum(
            record.mission_utility
            for record in records
        ),

        "feasible": sum(
            record.workloads_completed
            for record in records
        ),

        "infeasible": sum(
            record.workloads_infeasible
            for record in records
        ),

        "adaptations": sum(
            record.adaptations
            for record in records
        ),

        "migrations": sum(
            record.migrations
            for record in records
        ),

        "degradations": sum(
            record.degradations
            for record in records
        ),

        "fallbacks": sum(
            record.fallbacks
            for record in records
        ),

        "suspensions": sum(
            record.suspensions
            for record in records
        ),

        "migration_cost": sum(
            decision.get("details", {}).get("migration_cost", 0.0)
            for record in records
            for decision in record.decisions
        ),
    }


# ============================================================
# FEASIBILITY RATE
# ============================================================

def feasibility_rate(records):

    feasible = sum(
        r.workloads_completed
        for r in records
    )

    infeasible = sum(
        r.workloads_infeasible
        for r in records
    )


    total = feasible + infeasible


    if total == 0:
        return 0.0


    return (
        feasible / total
    ) * 100


# ============================================================
# CRITICAL WORKLOAD PRESERVATION
# ============================================================

def critical_preservation_rate(
    records
):

    critical = {
        "Obstacle Detection",
        "Navigation"
    }


    total = 0
    preserved = 0


    for record in records:

        for decision in record.decisions:

            if decision.get(
                "workload"
            ) not in critical:

                continue


            total += 1


            location = decision.get(
                "location"
            )

            mode = decision.get(
                "mode"
            )


            if hasattr(
                mode,
                "value"
            ):

                mode = mode.value


            if (
                location is not None
                and mode in [
                    "Full",
                    "Reduced",
                    "Fallback",
                ]
            ):

                preserved += 1


    if total == 0:
        return 0.0


    return (
        preserved / total
    ) * 100


# ============================================================
# SCENARIO RESULTS
# ============================================================

def scenario_results(records):

    results = {}


    for record in records:

        scenario = record.scenario


        if scenario not in results:

            results[scenario] = {
                "utility": 0,
                "feasible": 0,
                "infeasible": 0,
            }


        results[
            scenario
        ]["utility"] += (
            record.mission_utility
        )


        results[
            scenario
        ]["feasible"] += (
            record.workloads_completed
        )


        results[
            scenario
        ]["infeasible"] += (
            record.workloads_infeasible
        )


    return results


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 100)
    print(
        "MISSION-AWARE ORCHESTRATION "
        "POLICY COMPARISON"
    )
    print("=" * 100)


    timeline = create_timeline()


    print(
        f"\nTotal simulation steps: "
        f"{len(timeline)}"
    )


    # ========================================================
    # RUN ALL FIVE POLICIES
    # ========================================================

    print(
        "\nRunning Static..."
    )

    static_records = run_policy(
        "Static",
        timeline
    )


    print(
        "Running QoS-Based..."
    )

    qos_records = run_policy(
        "QoS-Based",
        timeline
    )


    print(
        "Running Resource-Aware..."
    )

    resource_records = run_policy(
        "Resource-Aware",
        timeline
    )


    print(
        "Running Utility-Based..."
    )

    utility_records = run_policy(
        "Utility-Based",
        timeline
    )


    print(
        "Running Proposed..."
    )

    proposed_records = run_policy(
        "Proposed",
        timeline
    )


    # ========================================================
    # STORE ALL RESULTS
    # ========================================================

    records_by_policy = {

        "Static": static_records,

        "QoS-Based": qos_records,

        "Resource-Aware": resource_records,

        "Utility-Based": utility_records,

        "Proposed": proposed_records,
    }


    results = {

        policy: aggregate_results(
            records
        )

        for policy, records
        in records_by_policy.items()
    }


    # ========================================================
    # OVERALL RESULTS
    # ========================================================

    print("\n" + "=" * 100)
    print("OVERALL RESULTS")
    print("=" * 100)


    headers = [
        "Static",
        "QoS-Based",
        "Resource-Aware",
        "Utility-Based",
        "Proposed",
    ]


    print(
        f"\n{'Metric':<30}"
        f"{'Static':>15}"
        f"{'QoS-Based':>15}"
        f"{'Resource-Aware':>20}"
        f"{'Utility-Based':>18}"
        f"{'Proposed':>15}"
    )


    print("-" * 115)


    print(
        f"{'Total Mission Utility':<30}"
        f"{results['Static']['utility']:>15.2f}"
        f"{results['QoS-Based']['utility']:>15.2f}"
        f"{results['Resource-Aware']['utility']:>20.2f}"
        f"{results['Utility-Based']['utility']:>18.2f}"
        f"{results['Proposed']['utility']:>15.2f}"
    )


    print(
        f"{'Total Feasible Assignments':<30}"
        f"{results['Static']['feasible']:>15}"
        f"{results['QoS-Based']['feasible']:>15}"
        f"{results['Resource-Aware']['feasible']:>20}"
        f"{results['Utility-Based']['feasible']:>18}"
        f"{results['Proposed']['feasible']:>15}"
    )


    print(
        f"{'Total Infeasible Assignments':<30}"
        f"{results['Static']['infeasible']:>15}"
        f"{results['QoS-Based']['infeasible']:>15}"
        f"{results['Resource-Aware']['infeasible']:>20}"
        f"{results['Utility-Based']['infeasible']:>18}"
        f"{results['Proposed']['infeasible']:>15}"
    )


    print(
        f"{'Total Adaptations':<30}"
        f"{results['Static']['adaptations']:>15}"
        f"{results['QoS-Based']['adaptations']:>15}"
        f"{results['Resource-Aware']['adaptations']:>20}"
        f"{results['Utility-Based']['adaptations']:>18}"
        f"{results['Proposed']['adaptations']:>15}"
    )


    print(
        f"{'Total Migrations':<30}"
        f"{results['Static']['migrations']:>15}"
        f"{results['QoS-Based']['migrations']:>15}"
        f"{results['Resource-Aware']['migrations']:>20}"
        f"{results['Utility-Based']['migrations']:>18}"
        f"{results['Proposed']['migrations']:>15}"
    )


    print(
        f"{'Total Migration Cost':<30}"
        f"{results['Static']['migration_cost']:>15.2f}"
        f"{results['QoS-Based']['migration_cost']:>15.2f}"
        f"{results['Resource-Aware']['migration_cost']:>20.2f}"
        f"{results['Utility-Based']['migration_cost']:>18.2f}"
        f"{results['Proposed']['migration_cost']:>15.2f}"
    )


    print(
        f"{'Total Degradations':<30}"
        f"{results['Static']['degradations']:>15}"
        f"{results['QoS-Based']['degradations']:>15}"
        f"{results['Resource-Aware']['degradations']:>20}"
        f"{results['Utility-Based']['degradations']:>18}"
        f"{results['Proposed']['degradations']:>15}"
    )


    print(
        f"{'Total Fallbacks':<30}"
        f"{results['Static']['fallbacks']:>15}"
        f"{results['QoS-Based']['fallbacks']:>15}"
        f"{results['Resource-Aware']['fallbacks']:>20}"
        f"{results['Utility-Based']['fallbacks']:>18}"
        f"{results['Proposed']['fallbacks']:>15}"
    )


    print(
        f"{'Total Suspensions':<30}"
        f"{results['Static']['suspensions']:>15}"
        f"{results['QoS-Based']['suspensions']:>15}"
        f"{results['Resource-Aware']['suspensions']:>20}"
        f"{results['Utility-Based']['suspensions']:>18}"
        f"{results['Proposed']['suspensions']:>15}"
    )


    # ========================================================
    # FEASIBILITY
    # ========================================================

    print("\n" + "=" * 100)
    print("FEASIBILITY COMPARISON")
    print("=" * 100)


    print(
        f"\n{'Policy':<25}"
        f"{'Feasibility':>20}"
        f"{'Infeasibility':>20}"
        f"{'Critical Preservation':>25}"
    )


    print("-" * 95)


    for policy in headers:

        records = records_by_policy[
            policy
        ]


        feasible = feasibility_rate(
            records
        )


        infeasible = 100 - feasible


        critical = (
            critical_preservation_rate(
                records
            )
        )


        print(
            f"{policy:<25}"
            f"{feasible:>19.2f}%"
            f"{infeasible:>19.2f}%"
            f"{critical:>24.2f}%"
        )


    # ========================================================
    # SCENARIO RESULTS
    # ========================================================

    scenario_data = {

        policy: scenario_results(
            records
        )

        for policy, records
        in records_by_policy.items()
    }


    scenario_order = [
        "Normal",
        "Network Degradation",
        "Edge Overload",
        "Cloud Failure",
        "Resource Pressure",
        "Emergency Mission",
        "Severe Degradation",
        "Recovery",
    ]


    # ========================================================
    # SCENARIO UTILITY
    # ========================================================

    print("\n" + "=" * 100)
    print("SCENARIO-LEVEL MISSION UTILITY")
    print("=" * 100)


    print(
        f"\n{'Scenario':<25}"
        f"{'Static':>15}"
        f"{'QoS-Based':>15}"
        f"{'Resource-Aware':>20}"
        f"{'Utility-Based':>18}"
        f"{'Proposed':>15}"
    )


    print("-" * 115)


    for scenario in scenario_order:

        print(
            f"{scenario:<25}"
            f"{scenario_data['Static'].get(scenario, {'utility': 0})['utility']:>15.2f}"
            f"{scenario_data['QoS-Based'].get(scenario, {'utility': 0})['utility']:>15.2f}"
            f"{scenario_data['Resource-Aware'].get(scenario, {'utility': 0})['utility']:>20.2f}"
            f"{scenario_data['Utility-Based'].get(scenario, {'utility': 0})['utility']:>18.2f}"
            f"{scenario_data['Proposed'].get(scenario, {'utility': 0})['utility']:>15.2f}"
        )


    # ========================================================
    # SCENARIO FEASIBILITY
    # ========================================================

    print("\n" + "=" * 100)
    print("SCENARIO-LEVEL FEASIBILITY")
    print("=" * 100)


    print(
        f"\n{'Scenario':<25}"
        f"{'Static':>15}"
        f"{'QoS-Based':>15}"
        f"{'Resource-Aware':>20}"
        f"{'Utility-Based':>18}"
        f"{'Proposed':>15}"
    )


    print("-" * 115)


    for scenario in scenario_order:

        print(
            f"{scenario:<25}",
            end=""
        )


        for policy in headers:

            data = scenario_data[
                policy
            ].get(
                scenario,
                {
                    "feasible": 0,
                    "infeasible": 0,
                }
            )


            total = (
                data["feasible"]
                + data["infeasible"]
            )


            if total == 0:
                rate = 0.0
            else:
                rate = (
                    data["feasible"]
                    / total
                ) * 100


            print(
                f"{rate:>14.2f}%"
                if policy != "Resource-Aware"
                else f"{rate:>19.2f}%",
                end=""
            )


        print()


    # ========================================================
    # FINAL COMPARISON
    # ========================================================

    print("\n" + "=" * 100)
    print("FINAL FIVE-POLICY COMPARISON")
    print("=" * 100)


    print(
        f"\n{'Policy':<25}"
        f"{'Utility':>18}"
        f"{'Feasible':>15}"
        f"{'Infeasible':>15}"
        f"{'Feasibility %':>18}"
        f"{'Critical %':>15}"
    )


    print("-" * 110)


    for policy in headers:

        policy_results = results[
            policy
        ]


        feasible = feasibility_rate(
            records_by_policy[
                policy
            ]
        )


        critical = (
            critical_preservation_rate(
                records_by_policy[
                    policy
                ]
            )
        )


        print(
            f"{policy:<25}"
            f"{policy_results['utility']:>18.2f}"
            f"{policy_results['feasible']:>15}"
            f"{policy_results['infeasible']:>15}"
            f"{feasible:>17.2f}%"
            f"{critical:>14.2f}%"
        )


    # ========================================================
    # PROPOSED IMPROVEMENT
    # ========================================================

    proposed_utility = results[
        "Proposed"
    ]["utility"]


    print("\n" + "=" * 100)
    print("PROPOSED POLICY IMPROVEMENT")
    print("=" * 100)


    for baseline in [
        "Static",
        "QoS-Based",
        "Resource-Aware",
        "Utility-Based",
    ]:

        baseline_utility = results[
            baseline
        ]["utility"]


        if baseline_utility != 0:

            improvement = (
                (
                    proposed_utility
                    - baseline_utility
                )
                / baseline_utility
            ) * 100

        else:

            improvement = 0.0


        print(
            f"Mission utility improvement "
            f"vs {baseline}: "
            f"{improvement:.2f}%"
        )


    # ========================================================
    # INFEASIBILITY REDUCTION
    # ========================================================

    proposed_infeasible = results[
        "Proposed"
    ]["infeasible"]


    print()


    for baseline in [
        "Static",
        "QoS-Based",
        "Resource-Aware",
        "Utility-Based",
    ]:

        baseline_infeasible = results[
            baseline
        ]["infeasible"]


        if baseline_infeasible != 0:

            reduction = (
                (
                    baseline_infeasible
                    - proposed_infeasible
                )
                / baseline_infeasible
            ) * 100

        else:

            reduction = 0.0


        print(
            f"Infeasibility reduction "
            f"vs {baseline}: "
            f"{reduction:.2f}%"
        )


    # ========================================================
    # COMPLETE
    # ========================================================

    print("\n" + "=" * 100)
    print("FIVE-POLICY SIMULATION COMPLETE")
    print("=" * 100)
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()