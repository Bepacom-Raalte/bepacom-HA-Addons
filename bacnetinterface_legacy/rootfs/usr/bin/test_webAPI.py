"""Testing flask part of webAPI"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from webAPI import BACnetToDict, DictToBACnet, app, str_to_tuple

client = TestClient(app)


def test_BACnetToDict():
    BACnetDict = {
        ("device", 100): {
            ("analogInput", 1): {
                "objectIdentifier": ("analogInput", 1),
                "objectName": "Test Object",
                "objectType": "Analog Input",
            }
        }
    }
    expected_output = {
        "device:100": {
            "analogInput:1": {
                "objectIdentifier": ("analogInput", 1),
                "objectName": "Test Object",
                "objectType": "Analog Input",
            }
        }
    }
    assert BACnetToDict(BACnetDict) == expected_output


def test_DictToBACnet():
    dictionary = {
        "device:100": {
            "analogInput:1": {
                "objectIdentifier": ("analogInput", 1),
                "objectName": "Test Object",
                "objectType": "Analog Input",
            }
        }
    }
    expected_output = {
        ("device", 100): {
            ("analogInput", 1): {
                "objectIdentifier": ("analogInput", 1),
                "objectName": "Test Object",
                "objectType": "Analog Input",
            }
        }
    }
    assert DictToBACnet(dictionary) == expected_output


def test_str_to_tuple():
    input_str = "3:4"
    expected_output = ("3", 4)
    assert str_to_tuple(input_str) == expected_output


@pytest.mark.skip(reason="Don't want to bother getting template in here")
def test_webapp_html(client: TestClient = client):
    response = client.get("/webapp")
    assert response.status_code == 200


@pytest.mark.skip(reason="Don't want to bother getting template in here")
def test_subscriptions_html(client: TestClient = client):
    response = client.get("/subscriptions")
    assert response.status_code == 200


def test_get_entire_dict(client: TestClient = client):
    response = client.get("/apiv1/json")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_command_whois(client: TestClient = client):
    response = client.get("/apiv1/command/whois")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_command_iam(client: TestClient = client):
    response = client.get("/apiv1/command/iam")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_command_readall(client: TestClient = client):
    response = client.get("/apiv1/command/readall")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_get_deviceid(client: TestClient = client):
    response = client.get("/apiv1/device:100")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_get_deviceid_objectid(client: TestClient = client):
    response = client.get("/apiv1/device:100/device:100")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_get_deviceid_objectid_propertyid(client: TestClient = client):
    response = client.get("/apiv1/device:100/device:100/objectName")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_post_write_objectid_property(client: TestClient = client):
    response = client.get("/apiv1/device:100/analogValue?outOfService=true")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


@pytest.mark.asyncio
async def test_websocket(client: TestClient = client):
    # Connect to the WebSocket endpoint
    websocket = await client.websocket_connect("/ws")
    # Close the WebSocket connection
    await websocket.close()
