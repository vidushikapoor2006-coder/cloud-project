from dataclasses import dataclass, field
from typing import List, Optional

from models.workload import Workload
from models.resource import ResourceState
from models.mission import MissionState, NetworkState


@dataclass
class SystemState:

    mission: MissionState
    onboard: ResourceState
    edge_1: ResourceState
    edge_2: ResourceState
    cloud: ResourceState
    network: NetworkState
    workloads: List[Workload]
    evtol_position: float = 0.0
    # Edge radio coverage radius in km (None = unlimited, original model).
    coverage_radius_km: Optional[float] = None
    # Simulation step index (informational; used by look-ahead policies).
    time: int = 0
