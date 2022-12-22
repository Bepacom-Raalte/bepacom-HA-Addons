from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.wsgi import WSGIMiddleware
from flask import Flask, render_template
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
    #### DeviceID: ObjectID : ObjectName : Waarde
    #### Van iedere object willen we het volgende:
    ####    ObjectID
    ####    ObjectName
    ####    ObjectType
    ####    Description
    ####    PresentValue
    ####    OutOfService
    ####    Reliability
    ####    StatusFlags
    ####    Units
    propertyFilter = (
        'objectIdentifier', 
        'objectName', 
        'objectType',
        'description',
        'presentValue',
        'outOfService',
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

async def on_start():
    # Startup delay so BACnetIOHandler can subscribe safely to everything
    await asyncio.sleep(5)
    
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
async def nicepage():
    global BACnetDeviceDict
    return BACnetToDict(BACnetDeviceDict)

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
    write_task = asyncio.create_task(writer(websocket, updateEvent))
    websocket_helper_tasks.add(write_task)
    read_task = asyncio.create_task(reader(websocket, updateEvent))
    websocket_helper_tasks.add(read_task)
    update_monitor_task = asyncio.create_task(on_changed(updateEvent))
    websocket_helper_tasks.add(update_monitor_task)

    while True:
        try:
            await asyncio.sleep(1)
        except WebSocketDisconnect:
            sys.stdout.write("Exception")


async def writer(websocket: WebSocket, updateEvent: asyncio.Event):
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

async def reader(websocket: WebSocket, updateEvent: asyncio.Event):
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


async def on_changed(updateEvent: asyncio.Event):
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
