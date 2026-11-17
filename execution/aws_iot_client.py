"""
AWS IoT Core MQTT client for the proof-of-concept prototype (Section V).

Revision changes
----------------
* Credentials are no longer stored in the repository.  The endpoint and
  certificate paths are read from environment variables (see README):
      AWS_IOT_ENDPOINT, AWS_IOT_CLIENT_ID, AWS_IOT_TOPIC,
      AWS_IOT_ROOT_CA, AWS_IOT_CERT, AWS_IOT_PRIVATE_KEY
  Defaults reproduce the original configuration (endpoint, client id,
  topic, file names in execution/certs/) so the original deployment keeps
  working once the certificate files are placed there again.
* The SDK is imported lazily, so the simulator runs without AWSIoTPythonSDK.
* publish_mission() returns the wall-clock publish time [ms], which main.py
  logs separately from the orchestration decision time.
"""

import json
import os
import time

CERT_DIR = os.path.join(os.path.dirname(__file__), "certs")
_ORIGINAL_ID = "09ee25ccec44a55a8f9ba7090400195e52cd52be1765bfba37d44831c2e4ed94"

ENDPOINT = os.environ.get(
    "AWS_IOT_ENDPOINT", "a1s1hai2r99cwp-ats.iot.ap-south-1.amazonaws.com")
CLIENT_ID = os.environ.get("AWS_IOT_CLIENT_ID", "eVTOL-001")
TOPIC = os.environ.get("AWS_IOT_TOPIC", "evtol/mission")
ROOT_CA = os.environ.get("AWS_IOT_ROOT_CA",
                         os.path.join(CERT_DIR, "AmazonRootCA1.pem"))
CERTIFICATE = os.environ.get(
    "AWS_IOT_CERT", os.path.join(CERT_DIR, f"{_ORIGINAL_ID}-certificate.pem.crt"))
PRIVATE_KEY = os.environ.get(
    "AWS_IOT_PRIVATE_KEY", os.path.join(CERT_DIR, f"{_ORIGINAL_ID}-private.pem.key"))

_client = None


def _get_client():
    global _client
    if _client is None:
        from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient  # lazy import
        for path in (ROOT_CA, CERTIFICATE, PRIVATE_KEY):
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"AWS IoT credential file not found: {path}. "
                    "See README section 'AWS proof-of-concept'.")
        client = AWSIoTMQTTClient(CLIENT_ID)
        client.configureEndpoint(ENDPOINT, 8883)
        client.configureCredentials(ROOT_CA, PRIVATE_KEY, CERTIFICATE)
        client.configureOfflinePublishQueueing(-1)
        client.configureDrainingFrequency(2)
        client.configureConnectDisconnectTimeout(10)
        client.configureMQTTOperationTimeout(5)
        _client = client
    return _client


def connect():
    print("Connecting to AWS IoT...")
    _get_client().connect()
    print("Connected to AWS IoT")


def publish_mission(mission_id, workload, mode, mission_phase, location,
                    verbose=True):
    message = {
        "mission_id": mission_id,
        "workload": workload,
        "mode": mode,
        "mission_phase": mission_phase,
        "location": location,
    }
    t0 = time.perf_counter()
    _get_client().publish(TOPIC, json.dumps(message), 1)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if verbose:
        print("Published message:")
        print(json.dumps(message, indent=2))
    return elapsed_ms


def disconnect():
    _get_client().disconnect()
    print("Disconnected from AWS IoT")


if __name__ == "__main__":
    connect()
    publish_mission(
        mission_id="mission-python-001",
        workload="Weather Analysis",
        mode="Full",
        mission_phase="CRUISE",
        location="AWS_CLOUD",
    )
    time.sleep(2)
    disconnect()
