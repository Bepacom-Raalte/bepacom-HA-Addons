from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.wsgi import WSGIMiddleware
from flask import Flask, render_template
from typing import Union, Any
from queue import Queue
import threading
import asyncio
import json
import sys

#===================================================
# Global variables
#===================================================

BACnetDeviceDict = dict()
websocket_helper_tasks = set()
threadingUpdateEvent = threading.Event()
threadingWhoIsEvent = threading.Event()
writeQueue = Queue()

#===================================================
# BACnet functions
#===================================================

async def get_bacnet_dict():
    """ Returns BACnetDeviceList dictionary"""
    return BACnetDeviceDict()

#===================================================
# Helperfunctions
#===================================================

def is_json(string: str) -> bool:
    """Check if a string is JSON, returns a bool for True or False"""
    try:
        json.loads(string)
        sys.stdout.write("It's JSON\n")
        return True
    except ValueError:
        sys.stdout.write("It's not JSON\n")
        return False

def BACnetToDict(BACnetDict):
    """Convert the BACnet dict to something that can be converted to JSON"""
    #### DeviceID: ObjectID : Property : Waarde
    propertyFilter = (
        'objectIdentifier', 
        'objectName', 
        'objectType',
        'description',
        'presentValue',
        'outOfService',
        'eventState',
        'reliability',
        'statusFlags',
        'units'
        )
    devicesDict = {}

    for deviceID in BACnetDict.keys():
        deviceDict = {}
        deviceIDstr = ':'.join(map(str,deviceID))

        for objectID in BACnetDict[deviceID].keys():
            objectDict = {}
            if objectID in ('address', 'deviceIdentifier'):
                continue
            objectIDstr = ':'.join(map(str,objectID))

            for propertyID,value in BACnetDict[deviceID][objectID].items():
                if propertyID in propertyFilter:
                    if isinstance(value, (int, float, bool, str)):
                        objectDict.update({propertyID: value})
                    else:
                        objectDict.update({propertyID: str(value)})

            deviceDict.update({objectIDstr: objectDict})
        devicesDict.update({deviceIDstr: deviceDict})
    return devicesDict         

def DictToBACnet(dictionary: dict) -> dict:
    # Create a new dictionary with the converted keys
    converted_dict = {str_to_tuple(k): v for k, v in dictionary.items()}

    # Recursively convert the keys in any inner dictionaries
    for k, v in converted_dict.items():
        if isinstance(v, dict):
            # If any more keys are in : format, please convert
            if any(":" in key for key in converted_dict[k]):
                converted_dict[k] = DictToBACnet(v)
           
    return converted_dict

def str_to_tuple(input_str: str) -> tuple:
    split_str = input_str.split(":")
    return (split_str[0], int(split_str[1]))

async def on_start():
    # Startup delay so BACnetIOHandler can subscribe safely to everything
    await asyncio.sleep(4)
    
#===================================================
# Flask setup (WebUI)
#===================================================

flask_app = Flask("WebUI", template_folder='/usr/bin/templates')

@flask_app.route("/")
def flask_main():
    return render_template("index.html")

#===================================================
# FastAPI setup
#===================================================
app = FastAPI(on_startup=[on_start])

@app.get("/apiv1/json")
async def get_entire_dict():
    global BACnetDeviceDict
    return BACnetToDict(BACnetDeviceDict)

@app.get("/apiv1/{deviceid}")
async def read_devid_dict(deviceid: str):
    global BACnetDeviceDict
    var = BACnetToDict(BACnetDeviceDict)
    return var[deviceid]

@app.get("/apiv1/{deviceid}/{objectid}")
async def read_objid_dict(deviceid: str, objectid: str):
    global BACnetDeviceDict
    var = BACnetToDict(BACnetDeviceDict)
    for key in var[deviceid].keys():
        if key.lower() == objectid:
            objectid = key
    return var[deviceid][objectid]

@app.get("/apiv1/{deviceid}/{objectid}/{propertyid}")
async def read_objid_property(deviceid: str, objectid: str, propertyid: str):
    global BACnetDeviceDict
    var = BACnetToDict(BACnetDeviceDict)
    return var[deviceid][objectid][propertyid]

@app.post("/apiv1/{deviceid}/{objectid}")
async def write_objid_property(
    deviceid: str,
    objectid: str,
    objectIdentifier: Union[str, None] = None,
    objectName: Union[str, None] = None,
    objectType: Union[str, None] = None,
    description: Union[str, None] = None,
    presentValue: Union[int,float, str, None] = None,
    outOfService: Union[bool, None] = None,
    eventState: Union[str, None] = None,
    reliability: Union[str, None] = None,
    statusFlags: Union[str, None] = None,
    units: Union[str, None] = None,
    ):

    property_dict:dict[dict,Any] = {}
    dict_to_write:dict[dict, Any] = {}
    if objectIdentifier != None:
        property_dict.update({'objectIdentifier': objectIdentifier})
    if objectName != None:
        property_dict.update({'objectName': objectName})
    if objectType != None:
        property_dict.update({'objectType': objectType})
    if description != None:
        property_dict.update({'description': description})
    if presentValue != None:
        property_dict.update({'presentValue': presentValue})
    if outOfService != None:
        property_dict.update({'outOfService': outOfService})
    if eventState != None:
        property_dict.update({'eventState': eventState})
    if reliability != None:
        property_dict.update({'reliability': reliability})
    if statusFlags != None:
        property_dict.update({'statusFlags': statusFlags})
    if units != None:
        property_dict.update({'units': units})
    dict_to_write = {deviceid: {objectid: property_dict}}

    bacnet_dict = DictToBACnet(dict_to_write)
    global writeQueue
    # Send this dict to threading queue for processing and making a request through BACnet
    writeQueue.put(bacnet_dict)
    return True


@app.get("/apiv1/command/whois")
async def whoiscommand():
    threadingWhoIsEvent.set()
    return


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # This function will be called whenever a new client connects to the server
    updateEvent = asyncio.Event()
    await websocket.accept()
    # Start a task to write data to the websocket
    write_task = asyncio.create_task(websocket_writer(websocket, updateEvent))
    websocket_helper_tasks.add(write_task)
    read_task = asyncio.create_task(websocket_reader(websocket, updateEvent))
    websocket_helper_tasks.add(read_task)
    update_monitor_task = asyncio.create_task(on_value_changed(updateEvent))
    websocket_helper_tasks.add(update_monitor_task)

    while True:
        try:
            await asyncio.sleep(1)
        except WebSocketDisconnect:
            sys.stdout.write("Exception")


async def websocket_writer(websocket: WebSocket, updateEvent: asyncio.Event):
    global BACnetDeviceDict
    while True:
        try:
            await updateEvent.wait()
            await websocket.send_json(BACnetToDict(BACnetDeviceDict))
            updateEvent.clear()

        except (RuntimeError, asyncio.CancelledError) as error:
            sys.stdout.write(str(error))
            return
        except WebSocketDisconnect:
            sys.stdout.write("Exception Disconnect for writer")
            return

async def websocket_reader(websocket: WebSocket, updateEvent: asyncio.Event):
    while True:
        try:
            data = await websocket.receive()
            sys.stdout.write(str(data)+"\n")

            if data['type'] == "websocket.disconnect":
                for task in websocket_helper_tasks:                # Cancel read and write tasks when disconnecting
                    task.cancel()
                websocket_helper_tasks.clear()
                sys.stdout.write("Disconnected...\n")
                return
            if data['text'].lower() == 'update':
                sys.stdout.write("Update Event set\n")
                updateEvent.set()


        except (RuntimeError, asyncio.CancelledError) as error:
            sys.stdout.write(str(error))
            return
        except WebSocketDisconnect:
            sys.stdout.write("Exception Disconnect for reader")
            return


async def on_value_changed(updateEvent: asyncio.Event):
    global BACnetDeviceDict
    try:
        while True:
            if not threadingUpdateEvent.is_set():
                await asyncio.sleep(1)
            else:
                threadingUpdateEvent.clear()
                updateEvent.set()
                sys.stdout.write("Update set...\n")
    except:
        sys.stdout.write("Exited on_change\n")
        

# mounting flask into FastAPI
app.mount("/webapp", WSGIMiddleware(flask_app))
