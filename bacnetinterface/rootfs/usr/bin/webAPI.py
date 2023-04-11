"""API script for BACnet add-on."""
import asyncio
import json
import logging
import sys
import threading
from queue import Queue
from typing import Any, Union

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# ===================================================
# Global variables
# ===================================================

BACnetDeviceDict = dict()
subscription_id_to_object: dict
threadingUpdateEvent: threading.Event = threading.Event()
threadingWhoIsEvent: threading.Event = threading.Event()
threadingIAmEvent: threading.Event = threading.Event()
threadingReadAllEvent: threading.Event = threading.Event()
writeQueue: Queue = Queue()
subQueue: Queue = Queue()
activeSockets: list = []


def BACnetToDict(BACnetDict):
    """Convert the BACnet dict to something that can be converted to JSON."""
    propertyFilter = (
        "objectIdentifier",
        "objectName",
        "objectType",
        "description",
        "presentValue",
        "outOfService",
        "eventState",
        "reliability",
        "statusFlags",
        "units",
        "covIncrement",
        "vendorName",
        "modelName",
        "stateText",
        "numberOfStates",
        "notificationClass",
    )
    devicesDict = {}
    for deviceID in BACnetDict.keys():
        deviceDict = {}
        deviceIDstr = ":".join(map(str, deviceID))
        for objectID in BACnetDict[deviceID].keys():
            objectDict = {}
            if objectID in ("address", "deviceIdentifier"):
                continue
            objectIDstr = ":".join(map(str, objectID))
            for propertyID, value in BACnetDict[deviceID][objectID].items():
                if propertyID in propertyFilter:
                    if isinstance(
                        value, (int, float, bool, str, list, dict, tuple, None)
                    ):
                        objectDict.update({propertyID: value})
                    else:
                        objectDict.update({propertyID: str(value)})
            deviceDict.update({objectIDstr: objectDict})
        devicesDict.update({deviceIDstr: deviceDict})
    return devicesDict


def DictToBACnet(dictionary: dict) -> dict:
    """Create a new dictionary with the converted keys."""
    converted_dict = {str_to_tuple(k): v for k, v in dictionary.items()}
    # Recursively convert the keys in any inner dictionaries
    for k, v in converted_dict.items():
        if isinstance(v, dict):
            # If any more keys are in : format, please convert
            if any(":" in key for key in converted_dict[k]):
                converted_dict[k] = DictToBACnet(v)
    return converted_dict


def str_to_tuple(input_str: str) -> tuple:
    """Convert ObjectIdentifier string to tuple."""
    split_str = input_str.split(":")
    return (split_str[0], int(split_str[1]))


async def on_start():
    """Startup sequence of FastAPI."""
    await asyncio.sleep(4)


description = """
The Bepacom EcoPanel BACnet/IP Interface is so cool!

## Things

You can do things!

## More things

We have these things!

"""


app = FastAPI(
    on_startup=[on_start],
    title="Bepacom EcoPanel BACnet/IP Interface API",
    description=description,
    version="0.0.1",
    contact={
        "name": "Bepacom B.V.",
        "url": "https://www.bepacom.nl/contact/",
    },
)


templates = Jinja2Templates(directory="/usr/bin/templates")


@app.get("/webapp", response_class=HTMLResponse)
async def webapp(request: Request):
    """Index and main page of the add-on"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions(request: Request):
    """Page to see subscription ID's"""
    return templates.TemplateResponse(
        "subscriptions.html",
        {"request": request, "subscriptions": subscription_id_to_object},
    )


@app.get("/apiv1/json")
async def get_entire_dict():
    """Return all devices and their values."""
    global BACnetDeviceDict
    return BACnetToDict(BACnetDeviceDict)


@app.get("/apiv1/command/whois")
async def whois_command():
    """Send a Who Is Request over the BACnet network."""
    threadingWhoIsEvent.set()
    return "Command queued"


@app.get("/apiv1/command/iam")
async def iam_command():
    """Send an I Am Request over the BACnet network."""
    threadingIAmEvent.set()
    return "Command queued"


@app.get("/apiv1/command/readall")
async def read_all_command():
    """Send a Read Request to all devices on the BACnet network."""
    threadingReadAllEvent.set()
    return "Command queued"


# Any commands or not variable paths should go above here... FastAPI will use it as a variable if you make a new path below this.


@app.get("/apiv1/{deviceid}")
async def read_deviceid_dict(deviceid: str):
    """Read a device."""
    global BACnetDeviceDict
    var = BACnetToDict(BACnetDeviceDict)
    try:
        return var[deviceid]
    except Exception as e:
        return "Error: " + str(e)


@app.get("/apiv1/{deviceid}/{objectid}")
async def read_objectid_dict(deviceid: str, objectid: str):
    """Read an object from a device."""
    try:
        global BACnetDeviceDict
        var = BACnetToDict(BACnetDeviceDict)
        for key in var[deviceid].keys():
            if key.lower() == objectid:
                objectid = key
        return var[deviceid][objectid]
    except Exception as e:
        return "Error: " + str(e)


@app.get("/apiv1/{deviceid}/{objectid}/{propertyid}")
async def read_objectid_property(deviceid: str, objectid: str, propertyid: str):
    """Read a property of an object from a device."""
    global BACnetDeviceDict
    var = BACnetToDict(BACnetDeviceDict)
    try:
        return var[deviceid][objectid][propertyid]
    except Exception as e:
        return "Error: " + str(e)


@app.post("/apiv1/{deviceid}/{objectid}")
async def write_property(
    deviceid: str,
    objectid: str,
    objectIdentifier: Union[str, None] = None,
    objectName: Union[str, None] = None,
    objectType: Union[str, None] = None,
    description: Union[str, None] = None,
    presentValue: Union[int, float, str, None] = None,
    outOfService: Union[bool, None] = None,
    eventState: Union[str, None] = None,
    reliability: Union[str, None] = None,
    statusFlags: Union[str, None] = None,
    units: Union[str, None] = None,
    covIncrement: Union[int, float, None] = None,
):
    """Write to a property of an object from a device."""
    property_dict: dict[dict, Any] = {}
    dict_to_write: dict[dict, Any] = {}
    if objectIdentifier != None:
        property_dict.update({"objectIdentifier": objectIdentifier})
    if objectName != None:
        property_dict.update({"objectName": objectName})
    if objectType != None:
        property_dict.update({"objectType": objectType})
    if description != None:
        property_dict.update({"description": description})
    if presentValue != None:
        property_dict.update({"presentValue": presentValue})
    if outOfService != None:
        property_dict.update({"outOfService": outOfService})
    if eventState != None:
        property_dict.update({"eventState": eventState})
    if reliability != None:
        property_dict.update({"reliability": reliability})
    if statusFlags != None:
        property_dict.update({"statusFlags": statusFlags})
    if units != None:
        property_dict.update({"units": units})
    if covIncrement != None:
        property_dict.update({"covIncrement": covIncrement})

    if property_dict == {}:
        return "No property values"

    dict_to_write = {deviceid: {objectid: property_dict}}

    logging.debug("Received: " + str(dict_to_write) + " in write_property()")

    try:
        bacnet_dict = DictToBACnet(dict_to_write)
    except Exception as e:
        return "Error: " + str(e)

    global writeQueue
    # Send this dict to threading queue for processing and making a request through BACnet
    writeQueue.put(bacnet_dict)
    return "Successfully put in Write Queue"


@app.post("/apiv1/subscribe/{deviceid}/{objectid}")
async def subscribe_objectid(
    deviceid: str, objectid: str, confirmationType: str, lifetime: int
):
    """Subscribe to an object of a device."""
    try:
        subTuple = (
            str_to_tuple(deviceid),
            str_to_tuple(objectid),
            confirmationType,
            lifetime,
        )
        if not "device" in subTuple[0][0]:
            raise Exception("Device value is not a device")

    except Exception as e:
        logging.error(e + " on subscribe from API POST request")

    global subQueue
    # Send this tuple to threading queue for processing and making a request through BACnet
    subQueue.put(subTuple)

    return "Successfully put in Subscription Queue"


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """This function will be called whenever a new client connects to the server."""
    await websocket.accept()

    # Start a task to write data to the websocket
    write_task = asyncio.create_task(websocket_writer(websocket))

    activeSockets.append(websocket)

    while True:
        try:
            data = await websocket.receive()
            if data["type"] == "websocket.disconnect":
                write_task.cancel
                activeSockets.remove(websocket)
                logging.info("Disconnected gracefully...\n")
                return
            if data["type"] == "websocket.receive" and "device:" in data["text"]:
                message = data["text"]
                try:
                    message = json.loads(message)
                    bacnet_dict = DictToBACnet(message)
                    global writeQueue
                    # Send this dict to threading queue for processing and making a request through BACnet
                    writeQueue.put(bacnet_dict)
                except:
                    pass

        except (RuntimeError, asyncio.CancelledError) as error:
            write_task.cancel
            activeSockets.remove(websocket)
            logging.error("Disconnected with RuntimeError or CancelledError...\n")
            return
        except WebSocketDisconnect:
            write_task.cancel
            activeSockets.remove(websocket)
            logging.error("Disconnected with WebSocketDisconnect...\n")
            return
        except Exception as e:
            write_task.cancel
            activeSockets.remove(websocket)
            logging.error("Disconnected with Exception" + str(e) + "...\n")


async def websocket_writer(websocket: WebSocket):
    """Writer task for when a websocket is opened"""
    global BACnetDeviceDict
    await websocket.send_json(BACnetToDict(BACnetDeviceDict))
    while True:
        if threadingUpdateEvent.is_set():
            try:
                for websocket in activeSockets:
                    await websocket.send_json(BACnetToDict(BACnetDeviceDict))
                threadingUpdateEvent.clear()
            except (RuntimeError, asyncio.CancelledError) as error:
                logging.error(str(error))
                return
            except WebSocketDisconnect:
                logging.error("Exception Disconnect for writer")
                return
        else:
            await asyncio.sleep(1)
