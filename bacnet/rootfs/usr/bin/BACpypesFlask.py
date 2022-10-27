#========================================
# Importing...
#========================================

import sys
from threading import Thread, active_count, enumerate
from flask import Flask


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


#========================================
# some debugging
#========================================
_debug = 0
_log = ModuleLogger(globals())

#========================================
# globals
#========================================
this_application = None
devices = []
rsvp = (True, None, None)

app = Flask(__name__)

@app.route("/")
def index():
    return "<p>congrats, it's a webapp</p>"

#========================================
# Some notes
#========================================
        #
        #   do read device:0 as object, do propertyList'listOfObjectPropertyReferences' as property <-niet in sim
        #   do read device:0 as object, do objectList as property <- werkt
        #   do read device:0 as object, do structuredObjectList as property <-niet in sim
        #

#========================================
# Console application
#========================================
@bacpypes_debugging
class console(ConsoleCmd):
    
    #========================================
    # Commands for console
    #========================================
    def do_threads(self, *args):
        """shows active threads in this program"""
        print("Active threads: " + str(active_count()))
        print(enumerate())

    #========================================
    def do_devices(self, *args):
        """Prints amount of devices and info contained inside"""
        try:
            for device in devices:
                print("Device " + str(devices.index(device)))
                for x in device:
                    print(x)
                print('\n')
        except:
            print("No devices")


    #========================================
    def do_getproplist(self, args):
        for each in devices:
            this_application.get_PropertyList(each[1], each[7])


    #========================================
    def do_whois(self, args):
        """whois [ <addr> ] [ <lolimit> <hilimit> ]"""
        args = args.split()
        if _debug: console._debug("do_whois %r", args)

        #emptying list, so all active devices reply
        devices.clear()

        try:
            # gather the parameters
            if (len(args) == 1) or (len(args) == 3):
                addr = Address(args[0])
                del args[0]
            else:
                addr = GlobalBroadcast()

            if len(args) == 2:
                lolimit = int(args[0])
                hilimit = int(args[1])
            else:
                lolimit = hilimit = None

            # code lives in the device service
            this_application.who_is(lolimit, hilimit, addr)

        except Exception as error:
            console._exception("exception: %r", error)

    #========================================
    def do_iam(self, args):
        """iam"""
        args = args.split()
        if _debug: console._debug("do_iam %r", args)

        # code lives in the device service
        this_application.i_am()

    #========================================
    def do_read(self, args):
        args = args.split()
        try:
            addr, obj_id, prop_id = args[:3]
            obj_id = ObjectIdentifier(obj_id).value
            if prop_id.isdigit():
                prop_id = int(prop_id)

            datatype = get_datatype(obj_id[0], prop_id)
            if not datatype:
                raise ValueError("invalid property for object type")

            # build a request
            request = ReadPropertyRequest(
                objectIdentifier=obj_id,
                propertyIdentifier=prop_id,
                )

            # give request destination
            request.pduDestination = Address(addr)


            if len(args) == 4:
                request.propertyArrayIndex = int(args[3])
            if _debug: console._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: console._debug("    - iocb: %r", iocb)

            #Callback to IOCB. This will execute on response
            iocb.add_callback(this_application.on_Read)

            # give it to the application
            this_application.request_io(iocb)

        except Exception as error:
            console._exception("exception: %r", error)



    #========================================
    def do_readmultiple(self, args):
        """Read all <addr> <obj_id>"""
        args = args.split()
        try:
            addr = args[0]
            obj_id = args[1]
           # List of properties to get
            propRefList = [
                PropertyReference(propertyIdentifier=PropertyIdentifier('all').value), 
                #PropertyReference(propertyIdentifier=PropertyIdentifier('required').value),
                #PropertyReference(propertyIdentifier=PropertyIdentifier('optional').value),
                ]

            # List of what object to get properties of
            readAccesList = [ReadAccessSpecification(objectIdentifier= obj_id,listOfPropertyReferences= propRefList)]

            # Creating request of list
            request = ReadPropertyMultipleRequest(listOfReadAccessSpecs= readAccesList)

            #Address of where to send it to
            request.pduDestination = Address(addr)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: Application._debug("    - iocb: %r", iocb)

            # let us know when its complete
            iocb.add_callback(this_application.on_ReadMulti)

            # give it to the application
            this_application.request_io(iocb)
        except Exception as error:
            console._exception("exception: %r", error)



    #========================================
    def do_write(self, args):
        """write <addr> <objid> <prop> [ <indx> ]"""
        #write 0xc0a8a81ef0e2 analogValue:0 outOfService true
        # write 1 <0xc0a8a81ec94a> 2 <analogValue(can be number):1> 3 <presentValue(can be number)> 4
        # write 0xc0a8a81ec94a analogValue:0 outOfService true
        args = args.split()
        if _debug: console._debug("do_write %r", args)

        try:
            addr = args[0]
            obj_id = ObjectIdentifier(args[1]).value
            prop_id = PropertyIdentifier(args[2]).value

            if obj_id != ObjectIdentifier(obj_id):
                raise ValueError("Not an object ID")
            if prop_id != PropertyIdentifier(prop_id):
                raise ValueError("Not a property ID")
            if not args:
                raise ValueError("operation required")

            if len(args) == 4:
                value = args[3]
                print("value: " + str(value))
            elif len(args) == 5:
                value = args[4]
                print("value: " + str(value))
            if _debug: console._debug("    - request: %r", request)
            

            datatype = get_datatype(obj_id[0], prop_id)
            if not datatype:
                raise ValueError("invalid property for object type")

            # change atomic values into something encodeable, null is a special case
            if (value == 'null'):
                value = Null()
            elif issubclass(datatype, Atomic):
                if datatype is Integer:
                    value = int(value)
                elif datatype is Real:
                    value = float(value)
                elif datatype is Unsigned:
                    value = int(value)
                elif datatype is Boolean:
                    value = bool(value)
                value = datatype(value)

            # build a request
            request = WritePropertyRequest(
                objectIdentifier=obj_id,
                propertyIdentifier=prop_id,
                )

            request.pduDestination = Address(addr)

             # save the value
            request.propertyValue = Any()
            try:
                request.propertyValue.cast_in(value)
            except Exception as error:
                console._exception("WriteProperty cast error: %r", error)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: console._debug("    - iocb: %r", iocb)
            
            iocb.add_callback(this_application.on_Write)

            # give it to the application
            this_application.request_io(iocb)


        except Exception as error:
            console._exception("exception: %r", error)

    #========================================
    def do_whohas(self, args):
        """<lowlimit><highlimit><objID>"""
        # whohas 2:1 or whohas 0 300000 2:1
        # gather the parameters
        args = args.split()
        
        if (len(args) == 1):
            obj = args[0]
            low_limits = 0
            high_limits = 4194302
        elif(len(args) == 3):
            low_limits = args[0]
            high_limits = args[1]
            obj = args[2]
        else:
            raise TypeError("Incorrect arguments")      

        this_application.who_has(low_limits, high_limits, obj)

    #========================================
    def do_subscribe(self, args):
        """subscribe addr proc_id obj_id [ confirmed ] [ lifetime ]
        Generate a SubscribeCOVRequest and wait for the response.
        """
        # example: subscribe 0xc0a8a87ed64e 1 analogInput:0 true 10
        # it'll require confirmation, and lasts 10 seconds

        args = args.split()
        if _debug:
            console._debug("do_subscribe %r", args)

        try:
            addr, proc_id, obj_id = args[:3]
            obj_id = ObjectIdentifier(obj_id).value

            proc_id = int(proc_id)

            if len(args) >= 4:
                issue_confirmed = args[3]
                if issue_confirmed == "-":
                    issue_confirmed = None
                else:
                    issue_confirmed = issue_confirmed.lower() == "true"
                if _debug:
                    console._debug(
                        "    - issue_confirmed: %r", issue_confirmed
                    )
            else:
                issue_confirmed = None

            if len(args) >= 5:
                lifetime = args[4]
                if lifetime == "-":
                    lifetime = None
                else:
                    lifetime = int(lifetime)
                if _debug:
                    console._debug("    - lifetime: %r", lifetime)
            else:
                lifetime = None

            # build a request
            # request = SubscribeCOVRequest(
            #     subscriberProcessIdentifier=proc_id, monitoredObjectIdentifier=obj_id
            # )
            request = SubscribeCOVPropertyRequest(
                subscriberProcessIdentifier=proc_id,
                monitoredObjectIdentifier=obj_id,
                monitoredPropertyIdentifier=PropertyReference(propertyIdentifier=85),
                covIncrement=2
            )
            request.pduDestination = Address(addr)

            # optional parameters
            if issue_confirmed is not None:
                request.issueConfirmedNotifications = issue_confirmed
            if lifetime is not None:
                request.lifetime = lifetime

            if _debug:
                console._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug:
                console._debug("    - iocb: %r", iocb)

            iocb.add_callback(this_application.on_Subscribed)

            this_application.request_io(iocb)

        except Exception as e:
            console._exception("exception: %r", e)
        
#========================================
# adding services to the program
#========================================
class BIPS(BIPSimpleApplication,WhoHasIHaveServices, ChangeOfValueServices, DeviceCommunicationControlServices, FileServices,FileServicesClient,ReadWritePropertyMultipleServices): 
    print("Services added")

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

    #
    #========================================
    # do_ callbacks
    #========================================
    # Do this when receiving an I Am (helper function of app.indication... do_ + function on response. Can be compared to callback?)
    #========================================
    def do_IAmRequest(self, apdu):
        try:
            #Make list for device
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
                        

                        # Convert services into something readable
                        if prop_id == 'protocolServicesSupported':
                            value = ServicesSupported(value)
                            services = []
                            #x = key, y = value... Easy way to check for the value and append the key
                            for x,y in value.bitNames.items():
                                if value.value[y] == 1:
                                    services.append(x)
                            propertyList.append(services)
                        else:
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
    def do_IHaveRequest(self, apdu):
        print("AN I HAVE REQUEST?!!")
        print(apdu)

#========================================
#   Threads
#========================================
#   BACpypes thread
class BACpypesThread(Thread):

    def __init__(self):
        Thread.__init__(self)
        
    def run(self):
        _log.debug("running")

        run()

        _log.debug("fini")

    def stop(self):
        stop()
        self.join()

#class GUI(Thread):

#    def __init__(self):
#        Thread.__init__(self)

#    def run(self):

#        ui.run()

#    def stop(self):
#        stop()
#        self.join()


#========================================
#   __main__
#========================================
def main():
    global this_application
    global this_device

    # parse the command line arguments
    args = ConfigArgumentParser(description=__doc__).parse_args()

    if _debug: _log.debug("initialization")
    if _debug: _log.debug("    - args: %r", args)

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
    if _debug: _log.debug("    - this_application: %r", this_application)

    # make a console
    this_console = console()
    if _debug: _log.debug("    - this_console: %r", this_console)

    # make the thread object and start it
    bacpypes_thread = BACpypesThread()
    #

    app.run(host='0.0.0.0', debug=True)
    # main thread
    #   
    bacpypes_thread.start()
        

if __name__ == "__main__":
    main()

