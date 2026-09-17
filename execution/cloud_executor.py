import time


def execute_on_cloud(workload):

    start_time = time.time()

    print(
        f"[AWS CLOUD] Executing: {workload.name}"
    )

    # Simulated cloud processing
    time.sleep(0.1)

    result = {
        "workload": workload.name,
        "status": "completed",
        "execution_location": "AWS Cloud"
    }

    execution_time = time.time() - start_time

    result["execution_time"] = execution_time

    print(
        f"[AWS CLOUD] Completed: "
        f"{workload.name}"
    )

    return result