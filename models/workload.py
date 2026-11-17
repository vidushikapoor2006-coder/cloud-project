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

    # Nominal (declared) demands; compute/energy are scaled at run time by
    # the dynamic demand factor of the simulator (this revision).
    nominal_compute: float = None
    nominal_energy: float = None

    def __post_init__(self):
        if self.nominal_compute is None:
            self.nominal_compute = self.compute_requirement
        if self.nominal_energy is None:
            self.nominal_energy = self.energy_requirement

    def set_demand_factor(self, factor):
        self.compute_requirement = self.nominal_compute * factor
        self.energy_requirement = self.nominal_energy * factor
