from dataclasses import dataclass

def get_evtol_position(step):
    return min(step * 0.125, 10.0)

@dataclass
class SimulationStep:
    time: int
    scenario: str


def create_timeline():

    timeline = []

    # --------------------------------------------------
    # 0 - 9
    # Normal operation
    # --------------------------------------------------

    for t in range(0, 10):

        timeline.append(
            SimulationStep(
                t,
                "Normal"
            )
        )

    # --------------------------------------------------
    # 10 - 19
    # Network degradation
    # --------------------------------------------------

    for t in range(10, 20):

        timeline.append(
            SimulationStep(
                t,
                "Network Degradation"
            )
        )

    # --------------------------------------------------
    # 20 - 29
    # Edge overload
    # --------------------------------------------------

    for t in range(20, 30):

        timeline.append(
            SimulationStep(
                t,
                "Edge Overload"
            )
        )

    # --------------------------------------------------
    # 30 - 39
    # Cloud failure
    # --------------------------------------------------

    for t in range(30, 40):

        timeline.append(
            SimulationStep(
                t,
                "Cloud Failure"
            )
        )

    # --------------------------------------------------
    # 40 - 49
    # Moderate resource pressure
    # --------------------------------------------------

    for t in range(40, 50):

        timeline.append(
            SimulationStep(
                t,
                "Resource Pressure"
            )
        )

    # --------------------------------------------------
    # 50 - 59
    # Emergency mission
    # --------------------------------------------------

    for t in range(50, 60):

        timeline.append(
            SimulationStep(
                t,
                "Emergency Mission"
            )
        )

    # --------------------------------------------------
    # 60 - 69
    # Severe degradation
    # --------------------------------------------------

    for t in range(60, 70):

        timeline.append(
            SimulationStep(
                t,
                "Severe Degradation"
            )
        )

    # --------------------------------------------------
    # 70 - 79
    # Recovery
    # --------------------------------------------------

    for t in range(70, 80):

        timeline.append(
            SimulationStep(
                t,
                "Recovery"
            )
        )

    return timeline