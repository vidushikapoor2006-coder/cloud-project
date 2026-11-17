"""Factory for the simulated system, built from config.py (single source)."""

import config
from models.workload import Workload, Criticality
from models.resource import ResourceState
from models.mission import MissionState, MissionPhase, NetworkState
from models.state import SystemState


def create_workloads():
    return [
        Workload(
            name=s["name"],
            criticality=Criticality[s["criticality"]],
            deadline=s["deadline"],
            compute_requirement=s["cpu"],
            memory_requirement=s["memory"],
            energy_requirement=s["energy"],
            network_requirement=s["network"],
            state_size_mb=s["state_mb"],
        )
        for s in config.WORKLOAD_SPECS
    ]


def create_system(coverage_radius_km=None):
    """Create a fresh system in the original 'Normal' configuration."""
    cap = config.HOST_CAPACITY
    return SystemState(
        mission=MissionState(phase=MissionPhase.CRUISE, emergency=False),
        onboard=ResourceState("Onboard", cap["Onboard"][0], 20,
                              cap["Onboard"][1], 20, 100),
        edge_1=ResourceState("Edge_1", cap["Edge_1"][0], 30,
                             cap["Edge_1"][1], 25, 100),
        edge_2=ResourceState("Edge_2", cap["Edge_2"][0], 40,
                             cap["Edge_2"][1], 30, 100),
        cloud=ResourceState("AWS_Cloud", cap["AWS_Cloud"][0], 50,
                            cap["AWS_Cloud"][1], 40, 100),
        network=NetworkState(latency=50, bandwidth=100, packet_loss=1,
                             connected=True),
        workloads=create_workloads(),
        coverage_radius_km=coverage_radius_km,
    )
