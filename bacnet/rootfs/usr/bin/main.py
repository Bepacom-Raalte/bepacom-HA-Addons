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
from bacpypes.consolelogging import ConfigArgumentParser, ConsoleLogHandler

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
    def run(self, args):
        uvicorn.run(api.app, host=args.ini.webserv, port=port, log_level="debug")

#===================================================
# Main
#=================================================== 
def main():

    #===================================================
    # parse bacpypes.ini
    #===================================================
    args = ConfigArgumentParser(description=__doc__).parse_args()


    #===================================================
    # Zeroconf setup
    #===================================================
    info = ServiceInfo(
        "_bacnet._tcp.local.",
        "BACnet/IP Home Assistant Add-on._bacnet._tcp.local.",
        addresses=[socket.inet_aton(args.ini.address)],
        port=port,
        server="bacnetinterface.local.",
    )
    zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
    # Start service advertising
    zeroconf.register_service(info)


    #===================================================
    # Uvicorn server
    #===================================================
    server = uviThread(args=(args))
    server.start(args)


    #===================================================
    # BACnet server
    #===================================================
    bac.start()



if __name__=="__main__":
    main()