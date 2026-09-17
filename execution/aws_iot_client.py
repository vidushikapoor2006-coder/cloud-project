from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import json
import os
import time


# AWS IoT Core endpoint
ENDPOINT = "a1s1hai2r99cwp-ats.iot.ap-south-1.amazonaws.com"

# MQTT client ID
CLIENT_ID = "eVTOL-001"

# MQTT topic
TOPIC = "evtol/mission"


# Certificate directory
CERT_DIR = os.path.join(
    os.path.dirname(__file__),
    "certs"
)


# Certificate files
ROOT_CA = os.path.join(
    CERT_DIR,
    "AmazonRootCA1.pem"
)

CERTIFICATE = os.path.join(
    CERT_DIR,
    "09ee25ccec44a55a8f9ba7090400195e52cd52be1765bfba37d44831c2e4ed94-certificate.pem.crt"
)

PRIVATE_KEY = os.path.join(
    CERT_DIR,
    "09ee25ccec44a55a8f9ba7090400195e52cd52be1765bfba37d44831c2e4ed94-private.pem.key"
)


# Create MQTT client
client = AWSIoTMQTTClient(CLIENT_ID)


# Configure AWS IoT endpoint
client.configureEndpoint(
    ENDPOINT,
    8883
)


# Configure certificates
client.configureCredentials(
    ROOT_CA,
    PRIVATE_KEY,
    CERTIFICATE
)


# MQTT configuration
client.configureOfflinePublishQueueing(-1)
client.configureDrainingFrequency(2)
client.configureConnectDisconnectTimeout(10)
client.configureMQTTOperationTimeout(5)


def connect():
    print("Connecting to AWS IoT...")

    client.connect()

    print("Connected to AWS IoT")


def publish_mission(
    mission_id,
    workload,
    mode,
    mission_phase,
    location
):

    message = {
        "mission_id": mission_id,
        "workload": workload,
        "mode": mode,
        "mission_phase": mission_phase,
        "location": location
    }

    client.publish(
        TOPIC,
        json.dumps(message),
        1
    )

    print("Published message:")
    print(json.dumps(message, indent=2))


def disconnect():
    client.disconnect()

    print("Disconnected from AWS IoT")


if __name__ == "__main__":

    connect()

    publish_mission(
        mission_id="mission-python-001",
        workload="Weather Analysis",
        mode="Full",
        mission_phase="CRUISE",
        location="AWS_CLOUD"
    )

    time.sleep(2)

    disconnect()