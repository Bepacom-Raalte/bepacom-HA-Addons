#===================================================
# Importing from libraries
#=================================================== 
from threading import Thread
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from flask import Flask, jsonify, escape, request, render_template
from time import sleep
import socket
from time import sleep
from zeroconf import IPVersion, ServiceInfo, Zeroconf
import webAPI as api
import BacnetInterface as bac
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
    )
from bacpypes.errors import DecodingError
from bacpypes.primitivedata import Tag, ObjectIdentifier, Null, Atomic, Integer, Unsigned, Real, Boolean, CharacterString, BitString
from bacpypes.constructeddata import ArrayOf, Array, Any, SequenceOf
from bacpypes.app import BIPSimpleApplication
from bacpypes.object import get_object_class, get_datatype
from bacpypes.local.device import LocalDeviceObject
from bacpypes.basetypes import PropertyReference, PropertyIdentifier, PropertyValue, RecipientProcess, Recipient, EventType, ServicesSupported

#importing services
from bacpypes.service.device import WhoHasIHaveServices, DeviceCommunicationControlServices
from bacpypes.service.cov import ChangeOfValueServices
from bacpypes.service.file import FileServices, FileServicesClient
from bacpypes.service.object import ReadWritePropertyMultipleServices

#===================================================
# Global variables
#===================================================
host = "127.0.0.1"
port = 7813

this_application = None
devices = []
rsvp = (True, None, None)

#===================================================
# Threads
#=================================================== 
# Uvicorn thread
class uviThread(Thread):
    def run(self):
        uvicorn.run(api.app, host=host, port=port, log_level="debug")

#===================================================
# Main
#=================================================== 
def main():
    #===================================================
    # Zeroconf setup
    #===================================================
    #info = ServiceInfo(
    #    "_bacnet._tcp.local.",
    #    "BACnet/IP Home Assistant Add-on._bacnet._tcp.local.",
    #    addresses=[socket.inet_aton(host)],
    #    port=port,
    #    server="bacnetinterface.local.",
    #)
    #zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
    ## Start service advertising
    #zeroconf.register_service(info)


    #===================================================
    # Uvicorn server
    #===================================================
    #server = uviThread()
    #server.start()


    #===================================================
    # BACnet server
    #===================================================
    bac.main()



if __name__=="__main__":
    main()