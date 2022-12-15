from typing import Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.wsgi import WSGIMiddleware
from flask import Flask, jsonify, escape, request, render_template
import asyncio
import json
import sys

#===================================================
# Global variables
#===================================================
background_tasks = set()
BACnetDeviceList = dict()
updateEvent = asyncio.Event()
websocket_helper_tasks = set()

#===================================================
# BACnet functions
#===================================================

async def get_bacnet_dict():
    """ Returns BACnetDeviceList dictionary"""
    return BACnetDeviceList()


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

def get_diff(localjson : dict, receivedjson : dict) -> dict:
    """Get the difference of 2 dictionaries, returns a dictionary of the difference"""
    #Remove any entries that are not in the local BACnet data (it should never add anything else to the dictionary)
    listToPop = []
    for key in receivedjson.keys():
        if key not in localjson.keys():
            listToPop.append(key)
    sys.stdout.write("List of trash: " + str(listToPop) + "\n")

    for key in listToPop:
        receivedjson.pop(key)

    #Compare 2 sets
    localset = set(localjson.items())
    receivedset = set(receivedjson.items())
    difference = dict(localset ^ receivedset)

    return difference


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
app = FastAPI()

@app.get("/apiv1")
async def root():
    global BACnetDeviceList
    return json.dumps(BACnetDeviceList)

@app.get("/apiv1/nice")
async def nicepage():
    global BACnetDeviceList
    return {"fugg": "u"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # This function will be called whenever a new client connects to the server
    await websocket.accept()
    # Start a task to write data to the websocket
    updateEvent = asyncio.Event()
    write_task = asyncio.create_task(writer(websocket, updateEvent))
    websocket_helper_tasks.add(write_task)
    read_task = asyncio.create_task(reader(websocket, updateEvent))
    websocket_helper_tasks.add(read_task)
    update_monitor_task = asyncio.create_task(on_changed(updateEvent))
    websocket_helper_tasks.add(update_monitor_task)

    while True:
        try:
            await asyncio.sleep(0)
        except WebSocketDisconnect:
            sys.stdout.write("Exception")


async def writer(websocket: WebSocket, updateEvent: asyncio.Event):
    global BACnetDeviceList
    while True:
        try:
            await updateEvent.wait()
            sys.stdout.write("Update Event awaited\n")
            
            await websocket.send({"type": "websocket.send", "text": str(BACnetDeviceList)})
            sys.stdout.write("Sent it, Chief...\n")
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
            if data['text'] == 'update':
                sys.stdout.write("Update Event set\n")
                updateEvent.set()


        except (RuntimeError, asyncio.CancelledError) as error:
            sys.stdout.write(str(error))
            return
        except WebSocketDisconnect:
            sys.stdout.write("Exception Disconnect for reader")
            return


async def on_changed(updateEvent: asyncio.Event):
    OldValue: dict = {}
    global BACnetDeviceList
    while True:
        while OldValue == BACnetDeviceList:
            await asyncio.sleep(0.1)
        sys.stdout.write("Value Changed..." + str(BACnetDeviceList) + "\n")
        updateEvent.set()
        OldValue = BACnetDeviceList


#@app.websocket("/ws")
#async def websocket_endpoint(websocket: WebSocket):
#    await websocket.accept()
#    while True:
#        #if no new data to send:
#        data = await websocket.receive()
#        sys.stdout.write("Received data: " + str(data) + "\n")
#        if data['type'] == "websocket.receive":
#            if is_json(data['text']):
#                #This is JSON
#                #Compare BACnet data to JSON
#                difference = get_diff({"keyA": "valA", "keyB": "valB"},{"keyA": "valC", "keyB": "valD", "Bullshitkey": "Bullshitvalue"})
#                sys.stdout.write(str(difference) + "\n")

#                #Maybe can signal data is available. Make it a global variable and make it settable from the main.

#                pass
#            else:
#                #This isn't JSON
#                #Respond to commands
#                if data['text'] == "henlo":
#                    sys.stdout.write("henlo\n")
#                    pass

#        if data['type'] == "websocket.disconnect":
#            sys.stdout.write("Disconnected...\n")
#            return


# mounting flask into FastAPI
app.mount("/webapp", WSGIMiddleware(flask_app))
