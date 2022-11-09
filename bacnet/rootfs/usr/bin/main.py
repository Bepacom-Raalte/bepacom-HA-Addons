#===================================================
# Importing from libraries
#=================================================== 
import sys
from threading import Thread, active_count, enumerate
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from flask import Flask, jsonify, escape, request, render_template
from time import sleep
import socket
from time import sleep
from zeroconf import IPVersion, ServiceInfo, Zeroconf
import webAPI as api



from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ConfigArgumentParser, ConsoleLogHandler
from bacpypes.consolecmd import ConsoleCmd
from bacpypes.core import run, deferred, stop
from bacpypes.iocb import IOCB
from bacpypes.pdu import Address, GlobalBroadcast
from bacpypes.apdu import (
    ReadPropertyRequest, 
    ReadPropertyACK, 
    ReadPropertyMultipleRequest,
    ReadPropertyMultipleACK,
    ReadAccessSpecification,
    WritePropertyRequest,
    SimpleAckPDU,
    AbortPDU,
    RejectPDU,
    WhoIsRequest, 
    IAmRequest, 
    IHaveRequest, 
    WhoHasRequest, 
    WhoHasObject, 
    WhoHasLimits, 
    SubscribeCOVRequest, 
    SubscribeCOVPropertyRequest,
    PropertyReference,
    UnconfirmedRequestPDU, 
    )
from bacpypes.errors import DecodingError
from bacpypes.primitivedata import Tag, ObjectIdentifier, Null, Atomic, Integer, Unsigned, Real, Boolean, CharacterString, BitString
from bacpypes.constructeddata import ArrayOf, Array, Any, SequenceOf, List
from bacpypes.app import BIPSimpleApplication, ApplicationIOController
from bacpypes.object import get_object_class, get_datatype, PropertyError
from bacpypes.local.device import LocalDeviceObject
from bacpypes.basetypes import PropertyReference, PropertyIdentifier, PropertyValue, RecipientProcess, Recipient, EventType, ServicesSupported
from bacpypes.errors import ExecutionError, InconsistentParameters, MissingRequiredParameter, ParameterOutOfRange

#importing services
from bacpypes.service.device import WhoHasIHaveServices, DeviceCommunicationControlServices
from bacpypes.service.cov import ChangeOfValueServices
from bacpypes.service.file import FileServices, FileServicesClient
from bacpypes.service.object import ReadWritePropertyMultipleServices


import BacnetInterface as bac

#===================================================
# Global variables
#===================================================
webserv: str
port = 7813
extIP: str

this_application = None
devices = []
rsvp = (True, None, None)

_debug = 0
_log = ModuleLogger(globals())





#===================================================
# Threads
#=================================================== 
# Uvicorn thread
class uviThread(Thread):
    def run(self):
        uvicorn.run(api.app, host=webserv, port=port, log_level="debug", )

# BACpypes tread
class bacThread(Thread):
    def run(self):
        while True:
            bac.run()

#===================================================
# Main
#=================================================== 
def main():

    #===================================================
    # parse bacpypes.ini
    #===================================================
    args = ConfigArgumentParser(description=__doc__).parse_args()
    global webserv
    global extIP
    webserv = args.ini.webserv
    extIP = args.ini.address

    #===================================================
    # Zeroconf setup
    #===================================================
    info = ServiceInfo(
        "_bacnet._tcp.local.",
        "BACnet/IP Home Assistant Add-on "+str(args.ini.objectname)+"._bacnet._tcp.local.",
        addresses=[socket.inet_aton(extIP), socket.inet_aton('127.0.0.1') ],
        port=port,
        server="homeassistant.local.",
    )
    sys.stdout.write(str(info)+"\n")
    zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
    # Start service advertising
    zeroconf.register_service(info)
    

    #===================================================
    # Uvicorn server
    #===================================================
    server = uviThread()
    server.start()


    #===================================================
    # BACnet server
    #===================================================

    bac.run(args)

if __name__=="__main__":
    main()


