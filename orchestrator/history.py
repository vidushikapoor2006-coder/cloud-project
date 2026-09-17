from dataclasses import dataclass


@dataclass
class AdaptationEvent:
    workload: str
    previous_location: str
    previous_mode: str
    new_location: str
    new_mode: str
    adaptation_type: str
    scenario: str


def classify_adaptation(
    previous_location,
    previous_mode,
    new_location,
    new_mode
):

    location_changed = previous_location != new_location
    mode_changed = previous_mode != new_mode

    # No change at all
    if not location_changed and not mode_changed:
        return "No Change"

    # Workload returns to Full execution
    if new_mode == "Full":

        if location_changed:
            return "Migration + Recovery"

        return "Recovery"

    # Migration + degradation/fallback
    if location_changed and mode_changed:

        if new_mode == "Fallback":
            return "Migration + Fallback"

        if new_mode == "Reduced":
            return "Migration + Degradation"

        if new_mode == "Suspended":
            return "Migration + Suspension"

    # Pure migration
    if location_changed:
        return "Migration"

    # Pure mode change
    if mode_changed:

        if new_mode == "Fallback":
            return "Fallback"

        if new_mode == "Reduced":
            return "Degradation"

        if new_mode == "Suspended":
            return "Suspension"

    return "Adaptation"