"""API script for BACnet add-on."""
import asyncio
import codecs
import csv
import json
import logging
import random
import sys
import threading
from contextlib import asynccontextmanager
from io import StringIO
from queue import Queue
from random import randint
from typing import Annotated, Any, Union

from BACnetIOHandler import BACnetIOHandler
from bacpypes.basetypes import EngineeringUnits, ObjectTypesSupported
from fastapi import (FastAPI, File, Query, Request, Response, UploadFile,
                     WebSocket, WebSocketDisconnect, status)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from main import get_ingress_url
from pydantic.utils import deep_update

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
EDE_files: list = []


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
        "activeText",
        "inactiveText",
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager of FastAPI."""
    # Do wait for 10 seconds on startup
    await asyncio.sleep(5)
    yield
    # Do nothing on shutdown


description = """
The Bepacom EcoPanel BACnet/IP Interface is so cool!

## Things

You can do things!

## More things

We have these things!

"""


app = FastAPI(
    lifespan=lifespan,
    title="Bepacom EcoPanel BACnet/IP Interface API",
    description=description,
    version="0.2.0",
    contact={
        "name": "Bepacom B.V.",
        "url": "https://www.bepacom.nl/contact/",
    },
    root_path=get_ingress_url(),
)


templates = Jinja2Templates(directory="/usr/bin/templates")


@app.get("/webapp", response_class=HTMLResponse)
async def webapp(request: Request):
    """Index and main page of the add-on."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions(request: Request):
    """Page to see subscription ID's."""
    return templates.TemplateResponse(
        "subscriptions.html",
        {"request": request, "subscriptions": subscription_id_to_object},
    )


@app.get("/ede", response_class=HTMLResponse)
async def subscriptions(request: Request):
    """Page to see EDE files uploaded."""
    return templates.TemplateResponse(
        "ede.html",
        {"request": request, "files": EDE_files},
    )


@app.get("/apiv1/json")
async def get_entire_dict():
    """Return all devices and their values."""

    dict_to_send = BACnetToDict(BACnetDeviceDict)
    if EDE_files:
        for file in EDE_files:
            dict_to_send = deep_update(dict_to_send, file)
    return dict_to_send


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


@app.get("/apiv1/commissioning/ede")
async def read_ede_files():
    """Read currently uploaded EDE files."""
    return EDE_files


@app.post("/apiv1/commissioning/ede", status_code=status.HTTP_200_OK)
async def upload_ede_files(
    response: Response, EDE: UploadFile | None, stateTexts: UploadFile | None = None
):
    """Upload EDE files to show up as placeholder in the object lists."""

    object_keys = ObjectTypesSupported.bitNames
    bacnet_units = EngineeringUnits.enumerations
    deviceDict = {}
    liststart = False
    stateTextsList = []
    statecounter = 0

    if stateTexts:
        csvStateText = csv.reader(
            codecs.iterdecode(stateTexts.file, "utf-8"), delimiter=";"
        )
        for row in csvStateText:
            if statecounter >= 2:
                row.pop(0)
                stateTextsList.append(row)
            statecounter += 1

    csvEDE = csv.reader(codecs.iterdecode(EDE.file, "utf-8"), delimiter=";")

    for row in csvEDE:
        if liststart:
            dev_instance = row[1]
            obj_name = row[2]
            obj_type = None

            for key, value in object_keys.items():
                if int(value) == int(row[3]):
                    obj_type = key
                    break
                else:
                    continue

            if obj_type is None:
                continue

            obj_instance = row[4]
            desc = row[5]

            try:
                present_value = row[6]
            except:
                present_value = randint(0, 10)
            try:
                state_text = row[13]
            except:
                state_text = None

            try:
                for key, value in bacnet_units.items():
                    if row[14]:
                        pass
                    else:
                        unit = None
                        continue
                    if int(value) == int(row[14]):
                        unit = key
                        break
            except:
                unit = None

            obj_dict = {}
            obj_dict = {
                "objectIdentifier": [obj_type, obj_instance],
                "objectType": obj_type,
                "objectName": obj_name,
                "description": desc,
            }

            if stateTextsList and "binary" in obj_type:
                obj_dict["inactiveText"] = stateTextsList[int(state_text)][0]
                obj_dict["activeText"] = stateTextsList[int(state_text)][1]
            elif stateTextsList and state_text:
                obj_dict["stateText"] = stateTextsList[int(state_text) - 1]
                obj_dict["numberOfStates"] = len(stateTextsList[int(state_text) - 1])

            if unit:
                obj_dict["units"] = unit

            if obj_type == "device":
                obj_dict["modelName"] = "EDE File"
                obj_dict["vendorName"] = "Bepacom EcoPanel BACnet/IP Interface"
                obj_dict["description"] = "Placeholder"
            else:
                obj_dict["presentValue"]: present_value

            if obj_type in BACnetIOHandler.objectFilter or obj_type == "device":
                deviceDict = deep_update(
                    deviceDict,
                    {
                        f"device:{dev_instance}": {
                            f"{obj_type}:{obj_instance}": obj_dict
                        }
                    },
                )

        if row[0] == "# keyname":
            liststart = True

    if list(deviceDict)[0] in list(BACnetToDict(BACnetDeviceDict)):
        logging.warning("Device ID already in use.")
        response.status_code = status.HTTP_409_CONFLICT
        return "This device already exists as a device in the BACnet/IP network"

    for file in EDE_files:
        if file.keys() in deviceDict.keys():
            logging.warning("EDE already loaded.")
            response.status_code = status.HTTP_409_CONFLICT
            return "This device already exists as EDE file"

    EDE_files.append(deviceDict)

    return deviceDict


@app.delete("/apiv1/commissioning/ede")
async def delete_ede_file(device_ids: Annotated[list[str] | None, Query()] = None):
    """Delete EDE files to stop letting them show up in API calls."""
    logging.error(len(EDE_files))
    EDE_files[:] = [
        dictionary
        for dictionary in EDE_files
        if all(device not in dictionary for device in device_ids)
    ]
    logging.error(len(EDE_files))
    return True


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
                dict_to_send = BACnetToDict(BACnetDeviceDict)
                if EDE_files:
                    for file in EDE_files:
                        dict_to_send = deep_update(dict_to_send, file)
                for websocket in activeSockets:
                    await websocket.send_json(dict_to_send)
                threadingUpdateEvent.clear()
            except (RuntimeError, asyncio.CancelledError) as error:
                logging.error(str(error))
                return
            except WebSocketDisconnect:
                logging.error("Exception Disconnect for writer")
                return
        else:
            await asyncio.sleep(1)
