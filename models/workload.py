from dataclasses import dataclass
from enum import Enum


class Criticality(Enum):
    VERY_HIGH = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 1


class ExecutionMode(Enum):
    FULL = "Full"
    REDUCED = "Reduced"
    FALLBACK = "Fallback"
    SUSPENDED = "Suspended"


class Location(Enum):
    ONBOARD = "Onboard"
    EDGE_1 = "Edge_1"
    EDGE_2 = "Edge_2"
    CLOUD = "AWS_Cloud"


class WorkloadState(Enum):
    RUNNING = "Running"
    DEGRADED = "Degraded"
    FALLBACK = "Fallback"
    SUSPENDED = "Suspended"
    MIGRATING = "Migrating"
    RECOVERING = "Recovering"


@dataclass
class Workload:
    name: str
    criticality: Criticality
    deadline: float
    compute_requirement: float
    memory_requirement: float
    energy_requirement: float
    network_requirement: float
    state_size_mb: float = 1.0

    # Runtime state
    current_location: Location = Location.ONBOARD
    current_mode: ExecutionMode = ExecutionMode.FULL
    previous_location: Location = None
    previous_mode: ExecutionMode = None
    state: WorkloadState = WorkloadState.RUNNING