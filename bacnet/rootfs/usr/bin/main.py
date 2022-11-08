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
from ssdpy import SSDPServer

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
        
# SSDP thread
class ssdpThread(Thread):
    def run(self):
        sys.stdout.write("Starting SSDP service...\n")
        server = SSDPServer("bacnet-interface", location="http://" + extIP + ":7813/apiv1")
        server.serve_forever()

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
        "BACnet/IP Home Assistant Add-on2._bacnet._tcp.local.",
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
    server.start()


    #===================================================
    # SSDP Server 
    #===================================================
    ssdp = ssdpThread()
    ssdp.start()


    #===================================================
    # BACnet server
    #===================================================
    bac.start(args)



if __name__=="__main__":
    main()