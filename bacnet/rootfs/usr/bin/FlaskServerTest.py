
"""
This application presents a 'console' prompt to the user asking for Who-Is and I-Am
commands which create the related APDUs, then lines up the corresponding I-Am
for incoming traffic and prints out the contents.
"""

import sys

from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ConfigArgumentParser
from bacpypes.consolecmd import ConsoleCmd

from bacpypes.core import run, enable_sleeping

from bacpypes.pdu import Address, GlobalBroadcast
from bacpypes.apdu import WhoIsRequest, IAmRequest
from bacpypes.errors import DecodingError

from bacpypes.app import BIPSimpleApplication
from bacpypes.local.device import LocalDeviceObject

from threading import Thread

from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


def main():
    while True:
        app.run(host = '0.0.0.0' ,port=5000, debug= True, use_reloader=False)


if __name__ == "__main__":
    main()