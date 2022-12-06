from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.wsgi import WSGIMiddleware
from flask import Flask, jsonify, escape, request, render_template
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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive()
        sys.stdout.write("Received data: " + str(data) + "\n")
        if data['type'] == "websocket.receive":
            if is_json(data['text']):
                #This is JSON
                #Compare BACnet data to JSON
                difference = get_diff({"keyA": "valA", "keyB": "valB"},{"keyA": "valC", "keyB": "valD", "Bullshitkey": "Bullshitvalue"})
                sys.stdout.write(str(difference) + "\n")

                #Maybe can signal data is available. Make it a global variable and make it settable from the main.

                pass
            else:
                #This isn't JSON
                #Respond to commands
                if data['text'] == "henlo":
                    sys.stdout.write("henlo\n")
                    pass

        if data['type'] == "websocket.disconnect":
            sys.stdout.write("Disconnected...\n")
            return

# mounting flask into FastAPI
app.mount("/webapp", WSGIMiddleware(flask_app))
