#===================================================
# Importing from libraries
#=================================================== 
import sys
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
from bacpypes.consolelogging import ConfigArgumentParser, ConsoleLogHandler

#===================================================
# Global variables
#===================================================
webserv: str
port = 7813
extIP: str

this_application = None
devices = []
rsvp = (True, None, None)

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
        addresses=[socket.inet_aton(extIP)],
        port=port,
        server="bacnetinterface.local.",
    )
    sys.stdout.write(str(info)+"\n")
    zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
    # Start service advertising
    zeroconf.register_service(info)
    

    #===================================================
    # Uvicorn server
    #===================================================
    server = uviThread()
    #server.start()


    #===================================================
    # BACnet server
    #===================================================
    global this_application
    global this_device

    # make a device object
    this_device = bac.LocalDeviceObject(
        objectName=args.ini.objectname,
        objectIdentifier=int(args.ini.objectidentifier),
        maxApduLengthAccepted=int(args.ini.maxapdulengthaccepted),
        segmentationSupported=args.ini.segmentationsupported,
        vendorIdentifier=int(args.ini.vendoridentifier),
        )

    # provide max segments accepted if any kind of segmentation supported
    if args.ini.segmentationsupported != 'noSegmentation':
        this_device.maxSegmentsAccepted = int(args.ini.maxsegmentsaccepted)

    # make a simple application
    this_application = bac.Application(this_device, args.ini.address)

    BACnet = bacThread()
    BACnet.start()

if __name__=="__main__":
    main()