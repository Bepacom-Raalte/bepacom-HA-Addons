"""Main script for EcoPanel BACnet add-on."""


import logging
import sys
from collections.abc import Callable
from queue import Queue
from threading import Event, Thread
from typing import Any

import uvicorn
import webAPI as api
from BACnetIOHandler import BACnetIOHandler
from bacpypes.consolelogging import ConfigArgumentParser, ConsoleLogHandler
from bacpypes.core import deferred, enable_sleeping, run, stop
from bacpypes.local.device import LocalDeviceObject
from bacpypes.task import RecurringTask

webserv: str = "127.0.0.1"
port = 7813

this_application = None
devices = []
rsvp = (True, None, None)

_debug = 0
logging.basicConfig(format="%(levelname)s:    %(message)s", level=logging.WARNING)


class uviThread(Thread):
    """Thread for Uvicorn."""

    def run(self):
        uvicorn.run(api.app, host=webserv, port=port)


class EventWatcherTask(RecurringTask):
    """Checks if event is true. When it is, do callback."""

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
    """Checks if queue has items. When it has, do callback."""

    def __init__(self, queue: Queue(), callback: Callable, interval):
        RecurringTask.__init__(self, interval)
        self.queue = queue
        self.callback = callback

        # install it
        self.install_task()

    def process_task(self):
        while not self.queue.empty():
            queue_item = self.queue.get()
            self.callback(queue_item)
        else:
            return


class RefreshDict(RecurringTask):
    """Checks if queue has items. When it has, do callback."""

    def __init__(self, interval):
        RecurringTask.__init__(self, interval)

        # install it
        self.install_task()

    def process_task(self):
        this_application.read_entire_dict()


def write_from_dict(dict_to_write: dict):
    """Write to object from a dict received by API"""
    deviceID = get_key(dict_to_write)
    for object in dict_to_write[deviceID]:
        for property in dict_to_write[deviceID][object]:
            prop_value = dict_to_write[deviceID][object].get(property)
            logging.info("Writing to " + str(object) + " + " + str(property))
            this_application.WriteProperty(
                object, property, prop_value, this_application.dev_id_to_addr(deviceID)
            )


def sub_from_tuple(subTuple: tuple):
    this_application.COVSubscribe(
        objectid=subTuple[0],
        address=subTuple[1],
        confirmationType=subTuple[2],
        lifetime=subTuple[4],
    )


def get_key(dictionary: dict) -> str:
    """Return the first key"""
    for key, value in dictionary.items():
        return key


def main():

    args = ConfigArgumentParser(description=__doc__).parse_args()

    server = uviThread()
    server.start()

    global this_application
    global this_device

    # make a device object
    this_device = LocalDeviceObject(
        objectName=args.ini.objectname,
        objectIdentifier=int(args.ini.objectidentifier),
        maxApduLengthAccepted=int(args.ini.maxapdulengthaccepted),
        segmentationSupported=args.ini.segmentationsupported,
        vendorIdentifier=int(args.ini.vendoridentifier),
        description="BACnet Add-on for Home Assistant",
    )

    # provide max segments accepted if any kind of segmentation supported
    if args.ini.segmentationsupported != "noSegmentation":
        this_device.maxSegmentsAccepted = int(args.ini.maxsegmentsaccepted)

    # make a simple application
    this_application = BACnetIOHandler(this_device, args.ini.address)
    logging.info("Starting BACnet device on " + args.ini.address + "\n")

    # Coupling of FastAPI and BACnetIOHandler
    api.BACnetDeviceDict = this_application.BACnetDeviceDict
    api.threadingUpdateEvent = this_application.updateEvent
    api.subscription_id_to_object = this_application.id_to_object
    who_is_watcher = EventWatcherTask(
        api.threadingWhoIsEvent, this_application.who_is, 2000
    )
    i_am_watcher = EventWatcherTask(api.threadingIAmEvent, this_application.i_am, 2000)
    read_watcher = EventWatcherTask(
        api.threadingReadAllEvent, this_application.read_entire_dict, 2000
    )
    write_queue_watcher = QueueWatcherTask(api.writeQueue, write_from_dict, 1000)
    sub_queue_watcher = QueueWatcherTask(api.subQueue, sub_from_tuple, 1000)
    dict_refresher = RefreshDict(60000)

    while True:
        run()


if __name__ == "__main__":
    main()
