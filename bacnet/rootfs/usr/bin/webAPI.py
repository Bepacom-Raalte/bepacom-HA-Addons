from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.wsgi import WSGIMiddleware
from flask import Flask, jsonify, escape, request, render_template
import asyncio
import json
import sys


#===================================================
# Flask setup (WebUI)
#===================================================
flask_app = Flask("WebUI", template_folder='/usr/bin/templates')

@flask_app.route("/")
def flask_main():
    return render_template("index.html")


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
# FastAPI setup
#===================================================
app = FastAPI()

@app.get("/apiv1")
async def root():
    
    return {"message": "Hello World"}

@app.get("/apiv1/nice")
async def nicepage():
    return {"fugg": "u"}

websocket_helper_tasks = set()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # This function will be called whenever a new client connects to the server
    await websocket.accept()
    # Start a task to write data to the websocket
    write_task = asyncio.create_task(writer(websocket))
    websocket_helper_tasks.add(write_task)
    read_task = asyncio.create_task(reader(websocket))
    websocket_helper_tasks.add(read_task)

    while True:
        try:
            await asyncio.sleep(1)
        except WebSocketDisconnect:
            sys.stdout.write("Exception")


async def writer(websocket):
    while True:
        try:
            await websocket.send_text("Hello from the server!")
            await asyncio.sleep(5)  # Wait for 5 second before sending the next message

        except (RuntimeError, asyncio.CancelledError) as error:
            sys.stdout.write(str(error))
            return
        except WebSocketDisconnect:
            sys.stdout.write("Exception Disconnect for writer")
            return

async def reader(websocket):
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

        except (RuntimeError, asyncio.CancelledError) as error:
            sys.stdout.write(str(error))
            return
        except WebSocketDisconnect:
            sys.stdout.write("Exception Disconnect for reader")
            return

# mounting flask into FastAPI
app.mount("/webapp", WSGIMiddleware(flask_app))
