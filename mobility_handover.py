from models.workload import Workload, Criticality, Location, ExecutionMode
from models.resource import ResourceState
from models.mission import MissionState, MissionPhase, NetworkState
from models.state import SystemState
from orchestrator.decision import calculate_migration_cost
from orchestrator.utility import calculate_score
from orchestrator.feasibility import get_feasible_actions


def create_handover_system():
    workload = Workload(
        name="Weather Analysis",
        criticality=Criticality.HIGH,
        deadline=200,
        compute_requirement=20,
        memory_requirement=15,
        energy_requirement=8,
        network_requirement=20,
        state_size_mb=1.0,
    )
    return SystemState(
        mission=MissionState(MissionPhase.CRUISE, False),
        onboard=ResourceState("Onboard", 100, 10, 100, 10, 100),
        edge_1=ResourceState("Edge_1", 100, 30, 100, 20, 100),
        edge_2=ResourceState("Edge_2", 100, 30, 100, 20, 100),
        cloud=ResourceState("AWS_Cloud", 200, 50, 200, 40, 100, available=False),
        network=NetworkState(50, 100, 1, True),
        workloads=[workload],
    )


def run():
    system = create_handover_system()
    workload = system.workloads[0]
    # Start with an already-running edge workload so the experiment measures
    # an actual E1 -> E2 handover rather than initial placement.
    workload.current_location = Location.EDGE_1
    workload.current_mode = ExecutionMode.FULL
    workload.previous_location = Location.EDGE_1
    workload.previous_mode = ExecutionMode.FULL

    print("===== MOBILITY / EDGE HANDOVER EXPERIMENT =====")
    print("Migration cost is applied only when changing execution location.")
    for position in [0, 2, 4, 6, 8, 9, 10]:
        system.evtol_position = float(position)
        candidates = []
        current_score = None
        if workload.current_location in (Location.EDGE_1, Location.EDGE_2):
            current_score = calculate_score(
                workload, workload.current_location, workload.current_mode, system
            )["score"]

        for location, mode in get_feasible_actions(workload, system):
            if location not in (Location.EDGE_1, Location.EDGE_2):
                continue

            base_score = calculate_score(
                workload, location, mode, system
            )["score"]
            migration = calculate_migration_cost(
                workload, workload.current_location, location, system
            )
            benefit = (
                None if current_score is None
                else base_score - current_score
            )

            # Initial placement/same location has no migration cost. For a
            # real handover, require the operating-score gain to exceed the
            # migration overhead.
            if location != workload.current_location and (
                benefit is None or benefit <= migration["migration_cost"]
            ):
                continue

            adjusted = base_score - migration["migration_cost"]
            candidates.append((adjusted, location, mode, migration, benefit))

        if not candidates:
            print(f"{position:>5.1f} km | NO BENEFICIAL HANDOVER")
            continue

        best = max(candidates, key=lambda x: x[0])
        migrated = workload.current_location != best[1]
        benefit_text = (
            "N/A" if best[4] is None else f"{best[4]:5.2f}"
        )
        print(
            f"{position:>5.1f} km | {best[1].value:<7} | {best[2].value:<7} | "
            f"Score={best[0]:7.2f} | Migration={"Yes" if migrated else "No"} | "
            f"Cost={best[3]["migration_cost"]:5.2f} | Benefit={benefit_text}"
        )
        workload.current_location = best[1]
        workload.current_mode = best[2]


if __name__ == "__main__":
    run()
