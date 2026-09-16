from dataclasses import dataclass
from typing import List

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