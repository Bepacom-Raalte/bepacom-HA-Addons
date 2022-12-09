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



#========================================
# adding services to the program
#========================================
class BIPS(BIPSimpleApplication,WhoHasIHaveServices, ChangeOfValueServices, DeviceCommunicationControlServices, FileServices,FileServicesClient,ReadWritePropertyMultipleServices): 
    sys.stdout.write("Services added\n")

#========================================
# BACpypes application
#========================================
class Application(BIPS):        #This is the engine of the program. It'll run all the commands given by the command prompt.
    def __init__(self, *args):
        if _debug: BIPSimpleApplication._debug("__init__ %r", args)
        BIPSimpleApplication.__init__(self, *args)
        self.startup()

        # keep track of requests to line up responses
        self._request = None

    #========================================
    #   Define custom calls...
    #========================================

    def request(self, apdu):

        if _debug: ApplicationIOController._debug("request %r", apdu)

        # if this is not unconfirmed request, tell the application to use
        # the IOCB interface
        if not isinstance(apdu, UnconfirmedRequestPDU):
            raise RuntimeError("use IOCB for confirmed requests")

        sys.stdout.write("We've got a request!!\n")

        # send it downstream
        super(ApplicationIOController, self).request(apdu)



    def who_has(self, low_limits = None, high_limits = None, object = None):
        if _debug: WhoHasIHaveServices.debug("who_has")

        # check for consistent parameters
        if (low_limits is not None):
            if (high_limits is None):
                print("Low value changed to 0")
                low_limits = None
            if (low_limits < 0) or (low_limits > 4194303):
                print("Low value changed to 0")
                low_limits = None

        if (high_limits is not None):
            if (high_limits is None):
                print("Low value changed to 0")
                low_limits = None
            if (high_limits < 0) or (high_limits > 4194303):
                print("High value changed to highest")
                high_limits = None

        #building object
        obj = WhoHasObject(objectIdentifier = object, objectName = None)

        #encoding limits to request format
        limits = WhoHasLimits(deviceInstanceRangeLowLimit = low_limits ,deviceInstanceRangeHighLimit = high_limits)

        #building request
        whoHas = WhoHasRequest(limits = limits, object = obj)

        #set destination
        whoHas.pduDestination = GlobalBroadcast()
        
        #Sending unconfirmed request (use IOCB for confirmed)
        self.request(whoHas)



    #========================================
    def do_IHaveRequest(self, apdu):
        print("AN I HAVE REQUEST?!!")
        print(apdu)

    #========================================
    def do_WhoIsRequest(self, apdu):
        """Respond to a Who-Is request."""

        sys.stdout.write("Responding to Who Is\n")

        # ignore this if there's no local device
        if not self.localDevice:
            sys.stdout.write("Not local device\n")
            return

        # extract the parameters
        low_limit = apdu.deviceInstanceRangeLowLimit
        high_limit = apdu.deviceInstanceRangeHighLimit

        # check for consistent parameters
        if (low_limit is not None):
            if (high_limit is None):
                raise MissingRequiredParameter("deviceInstanceRangeHighLimit required")
            if (low_limit < 0) or (low_limit > 4194303):
                raise ParameterOutOfRange("deviceInstanceRangeLowLimit out of range")
        if (high_limit is not None):
            if (low_limit is None):
                raise MissingRequiredParameter("deviceInstanceRangeLowLimit required")
            if (high_limit < 0) or (high_limit > 4194303):
                raise ParameterOutOfRange("deviceInstanceRangeHighLimit out of range")

        # see we should respond
        if (low_limit is not None):
            if (self.localDevice.objectIdentifier[1] < low_limit):
                return
        if (high_limit is not None):
            if (self.localDevice.objectIdentifier[1] > high_limit):
                return

        # generate an I-Am
        self.i_am(address=apdu.pduSource)



    def i_am(self, address=None):
        if _debug: console._debug("i_am")

        # this requires a local device
        if not self.localDevice:
            if _debug: console._debug("    - no local device")
            return

        # create a I-Am "response" back to the source
        iAm = IAmRequest(
            iAmDeviceIdentifier=self.localDevice.objectIdentifier,
            maxAPDULengthAccepted=self.localDevice.maxApduLengthAccepted,
            segmentationSupported=self.localDevice.segmentationSupported,
            vendorID=self.localDevice.vendorIdentifier,
            )

        # defaults to a global broadcast
        if not address:
            address = GlobalBroadcast()
        iAm.pduDestination = address
        if _debug: console._debug("    - iAm: %r", iAm)

        sys.stdout.write("Sending I Am\n")

        # away it goes
        self.request(iAm)


    #
    #========================================
    # do_ callbacks
    #========================================
    # Do this when receiving an I Am (helper function of app.indication... do_ + function on response. Can be compared to callback?)
    #========================================
    def do_IAmRequest(self, apdu):
        '''On receiving I Am request'''
        sys.stdout.write("I see an I Am request from " + str(apdu.pduSource) + " :DDDD\n")
        try:
            #Make list for device
            api.BACnetDeviceList = {
                                    "Source": apdu.pduSource,
                                    "Device ID": apdu.iAmDeviceIdentifier,
                                    "Vendor ID": apdu.vendorID
                                    }
            device = list()
            device.append('')                               # name
            device.append(apdu.pduSource)                   # source
            device.append(apdu.iAmDeviceIdentifier)         # device identifier
            device.append(apdu.maxAPDULengthAccepted)       # max APDU length
            device.append(apdu.segmentationSupported)       # Segmentation supported
            device.append(apdu.vendorID)                    # Vendor ID
        
            #make sure a device gets added to the list of devices when it's made
            if len(devices) == 0:
                devices.append(device)
            else:
                if device not in devices:
                    devices.append(device)
                else:
                    return

            # List of properties to get
            propRefList = [
                PropertyReference(propertyIdentifier=PropertyIdentifier('objectName').value), 
                PropertyReference(propertyIdentifier=PropertyIdentifier('description').value),
                PropertyReference(propertyIdentifier=PropertyIdentifier('objectList').value),
                #PropertyReference(propertyIdentifier=PropertyIdentifier('protocolVersion').value),
                #PropertyReference(propertyIdentifier=PropertyIdentifier('protocolRevision').value),
                PropertyReference(propertyIdentifier=PropertyIdentifier('protocolServicesSupported').value),
                ]

            # List of what object to get properties of
            readAccesList = [ReadAccessSpecification(objectIdentifier= device[2],listOfPropertyReferences= propRefList)]

            # Creating request of list
            request = ReadPropertyMultipleRequest(listOfReadAccessSpecs= readAccesList)

            #Address of where to send it to
            request.pduDestination = device[1]

            # make an IOCB
            iocb = IOCB(request)
            if _debug: Application._debug("    - iocb: %r", iocb)

            # let us know when its complete
            iocb.add_callback(self.on_Discovered)

            # give it to the application
            self.request_io(iocb)

        except Exception as error:
            print(error)

    #========================================
    def on_Discovered(self, iocb):
        if _debug: Application._debug("device_discovered %r", iocb)

        # do something for error/reject/abort
        if iocb.ioError:
            sys.stdout.write(str(iocb.ioError) + '\n')

        # do something for success
        elif iocb.ioResponse:
            apdu = iocb.ioResponse

            # should be a read multiple property ack
            if not isinstance(apdu, ReadPropertyMultipleACK):
                if _debug: Application._debug("    - not an ack")
                return
            #The ReadPropertyMultipleACK class consists of "listOfReadAccessResults" which is a sequence of the class ReadAccessResult

            AccessResultsList = apdu.listOfReadAccessResults[0]
            obj_id = apdu.listOfReadAccessResults[0].objectIdentifier
            propertyList = []

            for ReadAccessResult in AccessResultsList.listOfResults: #only one object, so don't need to check for multiple object IDs
                prop_id = ReadAccessResult.propertyIdentifier
                prop_array_index = ReadAccessResult.propertyArrayIndex

                if ReadAccessResult.readResult.propertyAccessError != None:
                    value = '-'
                else:
                    propertyValue = ReadAccessResult.readResult.propertyValue
                    datatype = get_datatype(obj_id[0], prop_id)

                    if not datatype:
                        value = '???'
                    else:
                    # special case for array parts, others are managed by cast_out
                        if issubclass(datatype, Array) and (prop_array_index is not None):
                            if prop_array_index == 0:
                                value = propertyValue.cast_out(Unsigned)
                            else:
                                value = propertyValue.cast_out(datatype.subtype)
                        else:
                            value = propertyValue.cast_out(datatype)
                        
                        propertyList.append(value)
                        

            # Append the propertylist to the device
            for device in devices:
                if device[1] == apdu.pduSource:
                    device[0] = propertyList[0]
                    propertyList.pop(0)
                    propertyList[1].pop(0) #remove device info from objectlist
                    device.extend(propertyList)


        # do something with nothing?
        else:
            if _debug: Application._debug("    - ioError or ioResponse expected")
            print("Failed to read name")


    #========================================
    def get_PropertyList(self, addr, objectList):
        for obj in objectList:

            # List of properties to get
            propRefList = [
                PropertyReference(propertyIdentifier=PropertyIdentifier('objectIdentifier').value), 
                PropertyReference(propertyIdentifier=PropertyIdentifier('objectName').value), 
                #PropertyReference(propertyIdentifier=PropertyIdentifier('objectType').value),
                #PropertyReference(propertyIdentifier=PropertyIdentifier('presentValue').value),
                PropertyReference(propertyIdentifier=PropertyIdentifier('description').value),
                #PropertyReference(propertyIdentifier=PropertyIdentifier('statusFlags').value),
                #PropertyReference(propertyIdentifier=PropertyIdentifier('eventState').value),
                PropertyReference(propertyIdentifier=PropertyIdentifier('reliability').value),
                PropertyReference(propertyIdentifier=PropertyIdentifier('outOfService').value),
                ]

            # List of what object to get properties of
            readAccesList = [ReadAccessSpecification(objectIdentifier= obj,listOfPropertyReferences= propRefList)]

            # Creating request of list
            request = ReadPropertyMultipleRequest(listOfReadAccessSpecs= readAccesList)

            # Setting address
            request.pduDestination = addr

            # make an IOCB
            iocb = IOCB(request)

            # let us know when its complete
            iocb.add_callback(self.on_PropertyList)

            # give it to the application
            self.request_io(iocb)


    #========================================
    def on_PropertyList(self, iocb):
    # do something for success
        if iocb.ioResponse:
            apdu = iocb.ioResponse
            propertyList = list()

            # Check for the right ACK
            if not isinstance(apdu, ReadPropertyMultipleACK):
                return
            
            # results per object in one request... which is just one object in this case
            for result in apdu.listOfReadAccessResults:
                obj_id = result.objectIdentifier
                # For every property...
                for element in result.listOfResults:
                    propertyIdentifier = element.propertyIdentifier
                    propertyArrayIndex = element.propertyArrayIndex

                    # check for an error
                    if element.readResult.propertyAccessError is not None:
                        value = '-'

                    else:
                        propertyValue = element.readResult.propertyValue
                        datatype = get_datatype(obj_id[0], propertyIdentifier)

                        if not datatype:
                                value = '?'
                        else:
                            # special case for array parts, others are managed by cast_out
                            if issubclass(datatype, Array) and (propertyArrayIndex is not None):
                                if propertyArrayIndex == 0:
                                    value = propertyValue.cast_out(Unsigned)
                                else:
                                    value = propertyValue.cast_out(datatype.subtype)
                            else:
                                value = propertyValue.cast_out(datatype)

                    propertyList.append(value)
            print(propertyList)

        # do something for error/reject/abort
        if iocb.ioError:
            print("Error property")
            if _debug:
                console._debug("    - error: %r", iocb.ioError)

    #========================================
    def on_Subscribed(self, iocb):
        # do something for success
        if iocb.ioResponse:
            print("Subscribed")
            apdu = iocb.ioResponse
            if _debug:
                console._debug("    - response: %r", iocb.ioResponse)

        # do something for error/reject/abort
        if iocb.ioError:
            print("Error subscribing")
            if _debug:
                console._debug("    - error: %r", iocb.ioError)

    #========================================
    # helper function do_ + (apdu.__class__.__name__) = do_ConfirmedCOVNotificationRequest
    def do_ConfirmedCOVNotificationRequest(self, apdu):
        if _debug:
            Application._debug(
                "do_ConfirmedCOVNotificationRequest %r", apdu
            )
        global rsvp

        print("{} changed\n".format(apdu.monitoredObjectIdentifier))
        for element in apdu.listOfValues:
            element_value = element.value.tagList
            if _debug:
                Application._debug("    - propertyIdentifier: %r", element.propertyIdentifier)
                Application._debug("    - value tag list: %r", element_value)

            if len(element_value) == 1:
                element_value = element_value[0].app_to_object().value

            print("    {} is {}".format(element.propertyIdentifier, str(element_value)))

        if rsvp[0]:
            # success
            response = SimpleAckPDU(context=apdu)
            if _debug:
                Application._debug("    - simple_ack: %r", response)

        elif rsvp[1]:
            # reject
            response = RejectPDU(reason=rsvp[1], context=apdu)
            if _debug:
                Application._debug("    - reject: %r", response)

        elif rsvp[2]:
            # abort
            response = AbortPDU(reason=rsvp[2], context=apdu)
            if _debug:
                Application._debug("    - abort: %r", response)

        # return the result
        self.response(response)

    #========================================
    def do_UnconfirmedCOVNotificationRequest(self, apdu):
        if _debug:
            Application._debug(
                "do_UnconfirmedCOVNotificationRequest %r", apdu
            )
        print(apdu.__class__.__name__)
        print("{} changed\n".format(apdu.monitoredObjectIdentifier))
        for element in apdu.listOfValues:
            element_value = element.value.tagList
            if len(element_value) == 1:
                element_value = element_value[0].app_to_object().value

            print("    {} is {}".format(element.propertyIdentifier, str(element_value)))

    #========================================
    # do_read callback, after reading it'll execute this
    def on_Read(self, iocb):
        # do something for error/reject/abort
        if iocb.ioError:
            sys.stdout.write(str(iocb.ioError) + "\n")

        # do something for success
        elif iocb.ioResponse:
            apdu = iocb.ioResponse

            # should be an ack
            if not isinstance(apdu, ReadPropertyACK):
                if _debug:
                    console._debug("    - not an ack")
                return

            # find the datatype
            datatype = get_datatype(
                apdu.objectIdentifier[0], apdu.propertyIdentifier
            )
            if _debug:
                console._debug("    - datatype: %r", datatype)
            if not datatype:
                raise TypeError("unknown datatype")

            # special case for array parts, others are managed by cast_out
            if issubclass(datatype, Array) and (
                apdu.propertyArrayIndex is not None
            ):
                if apdu.propertyArrayIndex == 0:
                    value = apdu.propertyValue.cast_out(Unsigned)
                else:
                    value = apdu.propertyValue.cast_out(datatype.subtype)
            else:
                value = apdu.propertyValue.cast_out(datatype)
            if _debug:
                console._debug("    - value: %r", value)

            sys.stdout.write(str(value) + "\n")
            if hasattr(value, "debug_contents"):
                value.debug_contents(file=sys.stdout)
            elif isinstance(value, list) and len(value) > 0:
                for i, element in enumerate(value):
                    sys.stdout.write("    [{}] {}\n".format(i, element))
                    if hasattr(element, "debug_contents"):
                        element.debug_contents(file=sys.stdout, indent=2)
            sys.stdout.flush()

        # do something with nothing?
        else:
            if _debug:
                console._debug(
                    "    - ioError or ioResponse expected"
                )

    #============================
    def on_ReadMulti(self, iocb):
        if _debug: Application._debug("device_discovered %r", iocb)

        # do something for error/reject/abort
        if iocb.ioError:
            sys.stdout.write(str(iocb.ioError) + '\n')

        # do something for success
        elif iocb.ioResponse:
            apdu = iocb.ioResponse

            # should be a read multiple property ack
            if not isinstance(apdu, ReadPropertyMultipleACK):
                if _debug: Application._debug("    - not an ack")
                return
            #The ReadPropertyMultipleACK class consists of "listOfReadAccessResults" which is a sequence of the class ReadAccessResult

            AccessResultsList = apdu.listOfReadAccessResults[0]
            obj_id = apdu.listOfReadAccessResults[0].objectIdentifier
            propertyList = []

            for ReadAccessResult in AccessResultsList.listOfResults: #only one object, so don't need to check for multiple object IDs
                prop_id = ReadAccessResult.propertyIdentifier
                prop_array_index = ReadAccessResult.propertyArrayIndex

                if ReadAccessResult.readResult.propertyAccessError != None:
                    value = '-'
                else:
                    propertyValue = ReadAccessResult.readResult.propertyValue
                    datatype = get_datatype(obj_id[0], prop_id)

                    if not datatype:
                        value = '???'
                    else:
                    # special case for array parts, others are managed by cast_out
                        if issubclass(datatype, Array) and (prop_array_index is not None):
                            if prop_array_index == 0:
                                value = propertyValue.cast_out(Unsigned)
                            else:
                                value = propertyValue.cast_out(datatype.subtype)
                        else:
                            value = propertyValue.cast_out(datatype)
                        print(value)
    #========================================
    # do_Write callback, after writing it'll execute this
    def on_Write(self, iocb):
        # do something for success
        try:
            if iocb.ioResponse:
                apdu = iocb.ioResponse
                # should be an ack
                if not isinstance(iocb.ioResponse, SimpleAckPDU):
                    if _debug: console._debug("    - not an ack")
                    return
                sys.stdout.write("ack\n")

            # do something for error/reject/abort
            if iocb.ioError:
                sys.stdout.write(str(iocb.ioError) + '\n')
        except Exception as error:
            console._exception("exception: %r", error)

    
    #========================================
    def do_ReadPropertyRequest(self, apdu):
        """Return the value of some property of one of our objects."""

        sys.stdout.write("Getting a read request...\n")

        # extract the object identifier
        objId = apdu.objectIdentifier

        # check for wildcard
        if (objId == ('device', 4194303)) and self.localDevice is not None:
            objId = self.localDevice.objectIdentifier

        # get the object
        obj = self.get_object_id(objId)

        if not obj:
            raise ExecutionError(errorClass='object', errorCode='unknownObject')

        try:
            # get the datatype
            datatype = obj.get_datatype(apdu.propertyIdentifier)

            # get the value
            value = obj.ReadProperty(apdu.propertyIdentifier, apdu.propertyArrayIndex)
            if value is None:
                raise PropertyError(apdu.propertyIdentifier)

            # change atomic values into something encodeable
            if issubclass(datatype, Atomic) or (issubclass(datatype, (Array, List)) and isinstance(value, list)):
                value = datatype(value)
            elif issubclass(datatype, Array) and (apdu.propertyArrayIndex is not None):
                if apdu.propertyArrayIndex == 0:
                    value = Unsigned(value)
                elif issubclass(datatype.subtype, Atomic):
                    value = datatype.subtype(value)
                elif not isinstance(value, datatype.subtype):
                    raise TypeError("invalid result datatype, expecting {0} and got {1}" \
                        .format(datatype.subtype.__name__, type(value).__name__))
            elif issubclass(datatype, List):
                value = datatype(value)
            elif not isinstance(value, datatype):
                raise TypeError("invalid result datatype, expecting {0} and got {1}" \
                    .format(datatype.__name__, type(value).__name__))

            # this is a ReadProperty ack
            resp = ReadPropertyACK(context=apdu)
            resp.objectIdentifier = objId
            resp.propertyIdentifier = apdu.propertyIdentifier
            resp.propertyArrayIndex = apdu.propertyArrayIndex

            # save the result in the property value
            resp.propertyValue = Any()
            resp.propertyValue.cast_in(value)

        except PropertyError:
            raise ExecutionError(errorClass='property', errorCode='unknownProperty')

        # return the result
        self.response(resp)



#===================================================
# Threads
#=================================================== 
# Uvicorn thread
class uviThread(Thread):
    def run(self):
        uvicorn.run(api.app, host=webserv, port=port, log_level="debug", )
        

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
        )

    # provide max segments accepted if any kind of segmentation supported
    if args.ini.segmentationsupported != 'noSegmentation':
        this_device.maxSegmentsAccepted = int(args.ini.maxsegmentsaccepted)

    # make a simple application
    this_application = Application(this_device, args.ini.address)
    sys.stdout.write("Starting BACnet device on " + args.ini.address + "\n")

    while True:
            run()

if __name__=="__main__":
    main()


