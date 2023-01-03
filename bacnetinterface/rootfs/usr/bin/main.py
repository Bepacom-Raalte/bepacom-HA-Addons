#===================================================
# Importing from libraries
#=================================================== 
from threading import Thread, Event
from collections.abc import Callable
from typing import Any
from queue import Queue
import uvicorn
import webAPI as api
import sys
import pickle
from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ConfigArgumentParser, ConsoleLogHandler
from bacpypes.core import run, deferred, stop, enable_sleeping
from bacpypes.local.device import LocalDeviceObject
from bacpypes.basetypes import PropertyReference, PropertyIdentifier, PropertyValue, RecipientProcess, Recipient, EventType, ServicesSupported
from bacpypes.task import RecurringTask
from BACnetIOHandler import BACnetIOHandler
from bacpypes.pdu import GlobalBroadcast, RemoteBroadcast, LocalBroadcast, Address

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
        uvicorn.run(api.app, host=webserv, port=port)

class EventWatcherTask(RecurringTask):
    """Checks if event is true. When it is, do callback"""
    def __init__(self, event: Event(), callback: Callable, interval):
        RecurringTask.__init__(self, interval)
        self.event = event
        self.callback = callback

        # install it
        self.install_task()
    def process_task(self):
        if self.event.is_set():
            self.callback()
            self.event.clear()

class QueueWatcherTask(RecurringTask):
    """Checks if queue has items. When it has, do callback"""
    def __init__(self, queue: Queue(), callback: Callable, interval):
        RecurringTask.__init__(self, interval)
        self.queue = queue
        self.callback = callback

        # install it
        self.install_task()
    def process_task(self):
        if self.queue.empty():
            return
        queue_item = self.queue.get()
        self.callback(queue_item)

class RefreshDict(RecurringTask):
    """Checks if queue has items. When it has, do callback"""
    def __init__(self, interval):
        RecurringTask.__init__(self, interval)

        # install it
        self.install_task()
    def process_task(self):
        for device, devicedata in this_application.BACnetDeviceDict.items():
            objectlist = []
            for object, objectdata in devicedata.items():
                if isinstance(objectdata, dict):
                    objectlist.append(object)
            this_application.ReadPropertyMultiple(
                objectList=objectlist,
                propertyList=this_application.propertyList,
                address=this_application.dev_id_to_addr(device)
                )

def write_from_dict(dict_to_write: dict):
    deviceID = get_key(dict_to_write)
    for object in dict_to_write[deviceID]:
        for property in dict_to_write[deviceID][object]:
            prop_value = dict_to_write[deviceID][object].get(property)
            this_application.WriteProperty(object, property, prop_value, this_application.dev_id_to_addr(deviceID))

def get_key(dictionary: dict) -> str:
    for key, value in dictionary.items():
        return key

        
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
    # Uvicorn server
    #===================================================
    server = uviThread()
    server.start()

    #===================================================
    # BACnet server
    #===================================================
    global this_application
    global this_device

    # make a device object
    this_device = LocalDeviceObject(
        objectName=args.ini.objectname,
        objectIdentifier=int(args.ini.objectidentifier),
        maxApduLengthAccepted=int(args.ini.maxapdulengthaccepted),
        segmentationSupported=args.ini.segmentationsupported,
        vendorIdentifier=int(args.ini.vendoridentifier),
        description="BACnet Add-on for Home Assistant"
        )

    # provide max segments accepted if any kind of segmentation supported
    if args.ini.segmentationsupported != 'noSegmentation':
        this_device.maxSegmentsAccepted = int(args.ini.maxsegmentsaccepted)

    # make a simple application
    this_application = BACnetIOHandler(this_device, args.ini.address)
    sys.stdout.write("Starting BACnet device on " + args.ini.address + "\n")

    # Coupling of FastAPI and BACnetIOHandler
    api.BACnetDeviceDict = this_application.BACnetDeviceDict
    api.threadingUpdateEvent = this_application.updateEvent
    who_is_watcher = EventWatcherTask(api.threadingWhoIsEvent, this_application.who_is, 2000)
    i_am_watcher = EventWatcherTask(api.threadingIAmEvent,this_application.i_am, 2000)
    write_queue_watcher = QueueWatcherTask(api.writeQueue, write_from_dict, 1000)
    dict_refresher = RefreshDict(60000)
    
    while True:
        run()

if __name__=="__main__":
    main()


