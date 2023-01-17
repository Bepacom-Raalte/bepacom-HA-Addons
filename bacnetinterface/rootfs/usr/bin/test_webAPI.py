"""Testing flask part of webAPI"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webAPI import app

client = TestClient(app)


def test_webapp_html(client: TestClient):
    response = client.get("/webapp")
    assert response.status_code == 200
    print("webapp succesful")
    # assert response.json() == {"message": "Hello World"}


def test_subscriptions_html(client: TestClient):
    response = client.get("/subscriptions")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_get_entire_dict(client: TestClient):
    response = client.get("/apiv1/json")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_command_whois(client: TestClient):
    response = client.get("/apiv1/command/whois")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_command_iam(client: TestClient):
    response = client.get("/apiv1/command/iam")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_command_readall(client: TestClient):
    response = client.get("/apiv1/command/readall")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_get_deviceid(client: TestClient):
    response = client.get("/apiv1/device:100")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_get_deviceid_objectid(client: TestClient):
    response = client.get("/apiv1/device:100/device:100")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_get_deviceid_objectid_propertyid(client: TestClient):
    response = client.get("/apiv1/device:100/device:100/objectName")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


def test_post_write_objectid_property(client: TestClient):
    response = client.get("/apiv1/device:100/analogValue?outOfService=true")
    assert response.status_code == 200
    # assert response.json() == {"message": "Hello World"}


@pytest.mark.asyncio
async def test_websocket(client: TestClient):
    # Connect to the WebSocket endpoint
    websocket = await client.websocket_connect("/ws")
    # Send a message through the WebSocket
    await websocket.send_json({"message": "Hello"})
    # Receive a message from the WebSocket
    message = await websocket.receive_json()
    assert message["message"] == "Hello"
    # Close the WebSocket connection
    await websocket.close()
