import time


def execute_locally(workload, mode):

    start_time = time.time()

    print(
        f"[ONBOARD] Executing: "
        f"{workload.name} "
        f"({mode.value})"
    )

    time.sleep(0.05)

    result = {
        "workload": workload.name,
        "status": "completed",
        "execution_location": "Onboard",
        "mode": mode.value
    }

    execution_time = time.time() - start_time

    result["execution_time"] = execution_time

    print(
        f"[ONBOARD] Completed: "
        f"{workload.name}"
    )

    return result