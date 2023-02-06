""" BACnet Add-on IO Handler"""

# IOHandler includes these functions as well

#    From Application class:
#    add_object()
#    delete_object()
#    get_object_id()
#    get_object_name()
#    iter_objects()
#    get_services_supported()
#    request()
#    indication()

#    From IOController class:
#    abort()
#    request_io()
#    process_io()
#    active_io()
#    complete_io()
#    abort_io()

#    From ReadWritePropertyServices:
#    do_ReadPropertyRequest()
#    do_WritePropertyRequest()
#    read_property_to_any()
#    read_property_to_result_element()

#    From ApplicationIOController class:
#    process_io()
#    request()
#    confirmation()

#    From WhoIsIAmServices:
#    startup()
#    who_is()
#    do_WhoIsRequest()
#    i_am()
#    do_IAmRequest()

#    From ReadWritePropertyMultipleServices:
#    do_ReadPropertyMultipleRequest

#    From BIPSimpleApplication class:
#    close_socket()

#    From ChangeOfValueServices:
#    add_subscription()
#    cancel_subscription()
#    subscription()
#    cov_notification()
#    cov_confirmation()
#    do_SubscribeCOVRequest()
#    do_SubscribeCOVPropertyRequest()


# Importing libraries
import sys
import threading
import logging
from typing import Any

import bacpypes.constructeddata
from bacpypes.apdu import (
    AbortPDU,
    PropertyReference,
    ReadAccessSpecification,
    ReadPropertyACK,
    ReadPropertyMultipleACK,
    ReadPropertyMultipleRequest,
    ReadPropertyRequest,
    RejectPDU,
    SimpleAckPDU,
    SubscribeCOVRequest,
    WritePropertyRequest,
)
from bacpypes.app import BIPSimpleApplication
from bacpypes.basetypes import (
    EventType,
    PropertyIdentifier,
    PropertyReference,
    PropertyValue,
    Recipient,
    RecipientProcess,
    ServicesSupported,
)
from bacpypes.constructeddata import AnyAtomic, Array
from bacpypes.errors import (
    ExecutionError,
    InconsistentParameters,
    MissingRequiredParameter,
    ParameterOutOfRange,
)
from bacpypes.iocb import IOCB
from bacpypes.object import get_datatype
from bacpypes.primitivedata import (
    Atomic,
    BitString,
    Boolean,
    CharacterString,
    Date,
    Double,
    Integer,
    Null,
    ObjectIdentifier,
    OctetString,
    Real,
    Time,
    Unsigned,
)
from bacpypes.service.cov import ChangeOfValueServices
from bacpypes.service.object import ReadWritePropertyMultipleServices

rsvp = (True, None, None)


class BACnetIOHandler(
    BIPSimpleApplication, ReadWritePropertyMultipleServices, ChangeOfValueServices
):
    """The class to handle BACnet communication."""

    # The following functions can be called from this class:
    # ReadProperty(Object ID, Prop ID, Address)                                   ->          Send a ReadPropertyRequest to designated address
    # ReadPropertyMultiple(ObjectID, PropIDList, Address)                         ->          Send a ReadPropertyMultipleRequest to designated address
    # WriteProperty(Object ID, Prop ID, Value, Address)                           ->          Send a WritePropertyRequest to designated address
    # COVSubscribe(SubscriptionID, Object ID, Confirmed/Unconfirmed, Address)     ->          Send a SubscribeCOVRequest to designated address
    # COVUnsubscribe(SubscriptionID, Object ID, Confirmed/Unconfirmed, Address)   ->          Send a SubscribeCOVRequest to designated address with time 1 to stop notifications
    # do_ConfirmedCOVNotificationRequest(apdu)                                    ->          Callback for Confirmed COV Notification
    # do_UnconfirmedCOVNotificationRequest(apdu)                                  ->          Callback for Unconfirmed COV Notification

    

    BACnetDeviceDict = {}
    objectFilter = [
        "accumulator",
        "analogInput",
        "analogOutput",
        "analogValue",
        "averaging",
        "binaryInput",
        "binaryOutput",
        "binaryValue",
        "multiStateInput",
        "multiStateOutput",
        "multiStateValue",
        "largeAnalogValue",
        "integerValue",
        "positiveIntegerValue",
        "lightingOutput",
        "notificationClass",
    ]
    propertyList = [
        PropertyReference(
            propertyIdentifier=PropertyIdentifier("objectIdentifier").value
        ),
        PropertyReference(propertyIdentifier=PropertyIdentifier("objectName").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("description").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("presentValue").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("statusFlags").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("outOfService").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("units").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("eventState").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("reliability").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("covIncrement").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("vendorName").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("modelName").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("stateText").value),
        PropertyReference(
            propertyIdentifier=PropertyIdentifier("numberOfStates").value
        ),
        PropertyReference(
            propertyIdentifier=PropertyIdentifier("notificationClass").value
        ),
        PropertyReference(propertyIdentifier=PropertyIdentifier("minPresValue").value),
        PropertyReference(propertyIdentifier=PropertyIdentifier("maxPresValue").value),
    ]

    id_to_object = {}
    object_to_id = {}
    available_ids = set()
    next_id = 1
    updateEvent = threading.Event()

    def __init__(self, *args) -> None:
        BIPSimpleApplication.__init__(self, *args)
        self.startup()
        self._request = None
        self.who_is()

    def update_object(self, objectID: tuple, deviceID: tuple, new_val: dict) -> None:
        """Update the object using both object ID and device ID."""
        for device in self.BACnetDeviceDict:
            if device == deviceID:
                self.updateEvent.set()
                try:
                    self.BACnetDeviceDict[deviceID][objectID].update(new_val)
                except:
                    self.BACnetDeviceDict[deviceID][objectID] = new_val

    def addr_to_dev_id(self, address: Any) -> tuple:
        """Convert address to corresponding device ID."""
        for key, value in self.BACnetDeviceDict.items():
            if value["address"] == address:
                return key

    def dev_id_to_addr(self, deviceID: tuple):
        """Convert address to corresponding device ID."""
        for key, value in self.BACnetDeviceDict.items():
            if key == deviceID:
                return value["address"]

    def assign_id(self, obj: tuple) -> int:
        """Assign an ID to the given object and return it."""
        if obj in self.object_to_id:
            # The object already has an ID, return it
            return self.object_to_id[obj]

        # Assign a new ID to the object
        if self.available_ids:
            # Use an available ID if there is one
            new_id = self.available_ids.pop()
        else:
            # Assign a new ID if there are no available IDs
            new_id = self.next_id
            self.next_id += 1

        self.id_to_object[new_id] = obj
        self.object_to_id[obj] = new_id
        return new_id

    def unassign_id(self, obj: tuple) -> None:
        """Remove the ID assignment for the given object."""
        if obj not in self.object_to_id:
            return

        # Remove the ID assignment for the object and add the ID to the available IDs set
        obj_id = self.object_to_id[obj]
        del self.id_to_object[obj_id]
        del self.object_to_id[obj]
        self.available_ids.add(obj_id)

    def read_entire_dict(self) -> None:
        """Send a read request for every object in every device."""
        for device, devicedata in self.BACnetDeviceDict.items():
            objectlist = []
            for object, objectdata in devicedata.items():
                if isinstance(objectdata, dict):
                    objectlist.append(object)
            self.ReadPropertyMultiple(
                objectList=objectlist,
                propertyList=self.propertyList,
                address=self.dev_id_to_addr(device),
            )

    def ReadProperty(
        self, objectID: ObjectIdentifier, propertyID: PropertyIdentifier, address: str
    ) -> bool:
        """Send a ReadPropertyRequest to designated address."""
        try:
            # make request
            request = ReadPropertyRequest(
                objectIdentifier=objectID,
                propertyIdentifier=propertyID,
                propertyArrayIndex=None,
            )

            # Set destination address
            request.pduDestination = address
            # make an IOCB
            iocb = IOCB(request)
            # let us know when its complete
            iocb.add_callback(self.on_ReadResult)
            # Send the request through
            self.request_io(iocb)

        except Exception as e:
            logging.error(str(e) + " from ReadProperty")
            return False
        else:
            return True

    def ReadPropertyMultiple(
        self, objectList: list, propertyList: list, address: str
    ) -> None:
        """Send a ReadPropertyMultipleRequest to designated address."""
        try:
            readAccessList = []
            # List of properties for a certain object
            for objects in objectList:
                ReadAccess = ReadAccessSpecification(
                    objectIdentifier=objects, listOfPropertyReferences=propertyList
                )
                readAccessList.append(ReadAccess)

            request = ReadPropertyMultipleRequest(listOfReadAccessSpecs=readAccessList)

            # Set destination address
            request.pduDestination = address
            # make an IOCB
            iocb = IOCB(request)
            # let us know when its complete
            iocb.add_callback(self.on_ReadMultipleResult)
            # Send the request through
            self.request_io(iocb)

        except Exception as e:
            logging.error(str(e) + " from ReadPropertyMultiple")
            return False
        else:
            return True

    def WriteProperty(self, objectID: Any, propertyID: Any, value, address) -> None:
        """Send a WritePropertyRequest to designated address."""

        try:
            # make the request
            request = WritePropertyRequest(
                objectIdentifier=objectID,
                propertyIdentifier=propertyID,
                propertyArrayIndex=None,
                propertyValue=None,
                priority=None,
            )

            datatype = get_datatype(objectID[0], propertyID)

            if issubclass(datatype, AnyAtomic):
                dtype, dvalue = value.split(":", 1)
                datatype = {
                    "b": Boolean,
                    "u": lambda x: Unsigned(int(x)),
                    "i": lambda x: Integer(int(x)),
                    "r": lambda x: Real(float(x)),
                    "d": lambda x: Double(float(x)),
                    "o": OctetString,
                    "c": CharacterString,
                    "bs": BitString,
                    "date": Date,
                    "time": Time,
                    "id": ObjectIdentifier,
                }[dtype]
                value = datatype(dvalue)

            elif issubclass(datatype, Atomic):
                if datatype is Integer:
                    value = int(value)
                elif datatype is Real:
                    value = float(value)
                elif datatype is Unsigned:
                    value = int(value)
                value = datatype(value)

            request.propertyValue = bacpypes.constructeddata.Any()
            request.propertyValue.cast_in(value)

            # Set destination address
            request.pduDestination = address

            # make an IOCB
            iocb = IOCB(request)

            # let us know when its complete
            iocb.add_callback(self.on_WriteResult)

            # Send the request through
            self.request_io(iocb)

        except Exception as e:
            logging.error(str(e) + " from WriteProperty")
            return False

    def COVSubscribe(self, objectID, confirmationType, address) -> None:
        """Send a SubscribeCOVRequest to designated address."""
        try:
            request = SubscribeCOVRequest(
                monitoredObjectIdentifier=ObjectIdentifier(objectID),
            )

            request.subscriberProcessIdentifier = self.assign_id(
                (objectID, self.addr_to_dev_id(address))
                )

            request.pduDestination = address

            if confirmationType == True:
                request.issueConfirmedNotifications = "true"
            else:
                request.issueConfirmedNotifications = None

            request.lifetime = 28799
            iocb = IOCB(request)
            iocb.add_callback(self.on_Subscribed)
            self.request_io(iocb)
        except Exception as e:
            logging.error(str(e) + "from COVSubscribe")
            return False

    def COVUnsubscribe(self, objectID, address):
        """Send a SubscribeCOVRequest to designated address with time 1 to stop notifications."""
        try:
            request = SubscribeCOVRequest(
                subscriberProcessIdentifier=int(
                    self.assign_id((objectID, self.addr_to_dev_id(address)))
                ),
                monitoredObjectIdentifier=objectID,
            )

            self.unsubscribe_id(objectID)

            request.pduDestination = address

            request.issueConfirmedNotifications = None

            iocb = IOCB(request)
            iocb.add_callback(self.on_Subscribed)
            self.request_io(iocb)

        except Exception as e:
            logging.error(str(e) + " from COVUnsubscribe")
            return False

    def do_IAmRequest(self, apdu):
        """ "Callback on detecting I Am response from other devices."""

        logging.info("I Am from " + str(apdu.iAmDeviceIdentifier))

        if self.localDevice.objectIdentifier == apdu.iAmDeviceIdentifier:
            return

        # If device in list, resubscribe and return
        if apdu.iAmDeviceIdentifier in self.BACnetDeviceDict:
            for object in self.BACnetDeviceDict[apdu.iAmDeviceIdentifier]:
                if isinstance(object, tuple):
                    self.COVSubscribe(object, True, apdu.pduSource)
            return

        BACnetDevice = {
            "address": apdu.pduSource,
            "deviceIdentifier": apdu.iAmDeviceIdentifier,
        }

        self.BACnetDeviceDict.update({apdu.iAmDeviceIdentifier: BACnetDevice})

        # Get device info
        self.ReadPropertyMultiple(
            objectList=[BACnetDevice["deviceIdentifier"]],
            propertyList=[
                PropertyReference(
                    propertyIdentifier=PropertyIdentifier("objectIdentifier").value
                ),
                PropertyReference(
                    propertyIdentifier=PropertyIdentifier("objectType").value
                ),
                PropertyReference(
                    propertyIdentifier=PropertyIdentifier("objectName").value
                ),
                PropertyReference(
                    propertyIdentifier=PropertyIdentifier("systemStatus").value
                ),
                PropertyReference(
                    propertyIdentifier=PropertyIdentifier("vendorName").value
                ),
                PropertyReference(
                    propertyIdentifier=PropertyIdentifier("vendorIdentifier").value
                ),
                PropertyReference(
                    propertyIdentifier=PropertyIdentifier("objectList").value
                ),
                PropertyReference(
                    propertyIdentifier=PropertyIdentifier("description").value
                ),
                PropertyReference(
                    propertyIdentifier=PropertyIdentifier("modelName").value
                ),
            ],
            address=BACnetDevice["address"],
        )

    def do_ConfirmedCOVNotificationRequest(self, apdu):
        """Callback on receiving Confirmed COV Notification."""

        global rsvp
        property_dict = {}
        try:
            for listvalue in apdu.listOfValues:
                datatype = get_datatype(
                    apdu.monitoredObjectIdentifier[0], listvalue.propertyIdentifier
                )

                value = listvalue.value.cast_out(datatype)
                property_dict.update({listvalue.propertyIdentifier: value})
            self.update_object(
                apdu.monitoredObjectIdentifier,
                apdu.initiatingDeviceIdentifier,
                property_dict,
            )

        except Exception as e:
            logging.error("Confirmed CoV Notification: " + str(e))

        if rsvp[0]:
            # success
            response = SimpleAckPDU(context=apdu)

        elif rsvp[1]:
            # reject
            response = RejectPDU(reason=rsvp[1], context=apdu)

        elif rsvp[2]:
            # abort
            response = AbortPDU(reason=rsvp[2], context=apdu)

        # return the result
        self.response(response)

    def do_UnconfirmedCOVNotificationRequest(self, apdu):
        """Callback on receiving Unconfirmed COV Notification."""

        global rsvp
        property_dict = {}
        for listvalue in apdu.listOfValues:
            datatype = get_datatype(
                apdu.monitoredObjectIdentifier[0], listvalue.propertyIdentifier
            )

            # Array things
            if issubclass(datatype, Array) and (
                listvalue.propertyArrayIndex is not None
            ):
                if listvalue.propertyArrayIndex == 0:
                    value = listvalue.value.cast_out(Unsigned)
                else:
                    value = listvalue.value.cast_out(datatype.subtype)
            else:
                value = listvalue.value.cast_out(datatype)
            property_dict.update({listvalue.propertyIdentifier: value})
        self.update_object(
            apdu.monitoredObjectIdentifier,
            apdu.initiatingDeviceIdentifier,
            property_dict,
        )

    def on_ReadMultipleResult(self, iocb: IOCB) -> None:
        """Callback for result after reading single or multiple properties."""

        def return_value_read_multiple(response) -> dict:
            objectdict = {}
            for objects in response.listOfReadAccessResults:
                object_id = objects.objectIdentifier
                propertydict = {}
                for properties in objects.listOfResults:
                    datatype = get_datatype(object_id[0], properties.propertyIdentifier)
                    # Check if datatype is valid
                    if datatype is None:
                        continue
                        # raise Exception('Invalid datatype')
                    if properties.readResult.propertyAccessError != None:
                        value = "-"
                    else:
                        # Array things
                        if issubclass(datatype, Array) and (
                            properties.propertyArrayIndex is not None
                        ):
                            if properties.propertyArrayIndex == 0:
                                value = properties.readResult.propertyValue.cast_out(
                                    Unsigned
                                )
                            else:
                                value = properties.readResult.propertyValue.cast_out(
                                    datatype.subtype
                                )
                        else:
                            value = properties.readResult.propertyValue.cast_out(
                                datatype
                            )
                        val_dict = {properties.propertyIdentifier: value}
                        propertydict.update(val_dict)
                objectdict.update({object_id: propertydict})
            return objectdict

        if iocb.ioError:
            logging.error(str(iocb.ioError) + " from " + str(iocb.ioError.pduSource) + "on read multiple result")
            if (
                iocb.args[0].listOfReadAccessSpecs[0].objectIdentifier[0] == "device"
                and len(iocb.args[0].listOfReadAccessSpecs) == 1
            ):
                # self.ReadProperty(iocb.args[0].listOfReadAccessSpecs[0].objectIdentifier,PropertyIdentifier('objectList'),iocb.ioError.pduSource)
                self.ReadPropertyMultiple(
                    objectList=[iocb.args[0].listOfReadAccessSpecs[0].objectIdentifier],
                    propertyList=self.propertyList,
                    address=iocb.ioError.pduSource,
                )
            else:
                objectList = []
                for spec in iocb.args[0].listOfReadAccessSpecs:
                    self.ReadPropertyMultiple(
                        objectList=[spec.objectIdentifier],
                        propertyList=self.propertyList,
                        address=iocb.ioError.pduSource,
                    )
            return
        # do something for success
        elif iocb.ioResponse:
            # should be a read property or read property multiple ack
            if not isinstance(iocb.ioResponse, ReadPropertyMultipleACK):
                logging.warning(str(iocb.ioResponse.apduAbortRejectReason))
                return

            response = iocb.ioResponse
            obj_dict = return_value_read_multiple(response)
            try:
                for result in response.listOfReadAccessResults:
                    if result.objectIdentifier[0] == "device":
                        if (
                            not result.objectIdentifier
                            in self.BACnetDeviceDict[result.objectIdentifier]
                        ):
                            self.update_object(
                                result.objectIdentifier,
                                self.addr_to_dev_id(response.pduSource),
                                obj_dict[result.objectIdentifier],
                            )

                            objectList = []
                            for object in self.BACnetDeviceDict[
                                result.objectIdentifier
                            ][result.objectIdentifier]["objectList"]:
                                if object[0] in self.objectFilter:
                                    objectList.append(object)

                            self.ReadPropertyMultiple(
                                objectList=objectList,
                                propertyList=[
                                    PropertyReference(
                                        propertyIdentifier=PropertyIdentifier(
                                            "all"
                                        ).value
                                    )
                                ],
                                address=self.BACnetDeviceDict[result.objectIdentifier][
                                    "address"
                                ],
                            )
                        else:
                            self.update_object(
                                result.objectIdentifier,
                                self.addr_to_dev_id(response.pduSource),
                                obj_dict[result.objectIdentifier],
                            )
                    else:
                        self.update_object(
                            result.objectIdentifier,
                            self.addr_to_dev_id(response.pduSource),
                            obj_dict[result.objectIdentifier],
                        )

                        if (
                            #(
                            #    result.objectIdentifier,
                            #    self.addr_to_dev_id(response.pduSource),
                            #)
                            #not in self.object_to_id
                            #and 
                            result.objectIdentifier[0] in self.objectFilter
                            and result.objectIdentifier[0] != "notificationClass"
                        ):
                            self.COVSubscribe(
                                result.objectIdentifier, True, response.pduSource
                            )
            except Exception as e:
                logging.error(str(e) + " from " + str(iocb.ioError.pduSource) + " on read multiple result")
                return False

    def on_ReadResult(self, iocb: IOCB) -> None:
        """Callback for result after reading single or multiple properties."""

        def return_value_read(response) -> dict:
            datatype = get_datatype(
                response.objectIdentifier[0], response.propertyIdentifier
            )
            # Check if datatype is valid
            if datatype is None:
                raise Exception("Invalid datatype")
            # Array things
            if issubclass(datatype, Array) and (
                response.propertyArrayIndex is not None
            ):
                if response.propertyArrayIndex == 0:
                    value = response.propertyValue.cast_out(Unsigned)
                else:
                    value = response.propertyValue.cast_out(datatype.subtype)
            else:
                value = response.propertyValue.cast_out(datatype)
            # Check for response.pduSource against dict to update value
            val_dict = {response.propertyIdentifier: value}
            return val_dict

        if iocb.ioError:
            logging.error(str(iocb.ioError) + " from " + str(iocb.ioError.pduSource) + " on read result")
            if iocb.args[0].listOfReadAccessSpecs[0].objectIdentifier[0] == "device":
                self.ReadProperty(
                    iocb.args[0].listOfReadAccessSpecs[0].objectIdentifier,
                    PropertyIdentifier("objectList"),
                    iocb.ioError.pduSource,
                )
            return

        # do something for success
        elif iocb.ioResponse:
            # should be a read property or read property multiple ack
            if not isinstance(iocb.ioResponse, ReadPropertyACK) and not isinstance(
                iocb.ioResponse, ReadPropertyMultipleACK
            ):
                logging.warning(
                    "No ACKs... " + iocb.ioResponse.apduAbortRejectReason + "\n"
                )
                return

            response = iocb.ioResponse
            try:
                val_dict = return_value_read(response)
                if response.objectIdentifier[0] == "device":
                    if (
                        not response.objectIdentifier
                        in self.BACnetDeviceDict[response.objectIdentifier]
                    ):
                        self.update_object(
                            response.objectIdentifier,
                            response.objectIdentifier,
                            val_dict,
                        )
                        objectList = []
                        for object in self.BACnetDeviceDict[response.objectIdentifier][
                            response.objectIdentifier
                        ]["objectList"]:
                            objectList.append(object)
                        self.ReadPropertyMultiple(
                            objectList=objectList,
                            propertyList=self.propertyList,
                            address=self.BACnetDeviceDict[response.objectIdentifier][
                                "address"
                            ],
                        )
                    else:
                        self.update_object(
                            response.objectIdentifier,
                            self.addr_to_dev_id(response.pduSource),
                            val_dict,
                        )
                else:
                    self.update_object(
                        response.objectIdentifier,
                        self.addr_to_dev_id(response.pduSource),
                        val_dict,
                    )

                    if (
                        #(
                        #    response.objectIdentifier,
                        #    self.addr_to_dev_id(response.pduSource),
                        #)
                        #not in self.object_to_id
                        #and 
                        response.objectIdentifier[0] in self.objectFilter
                        and response.objectIdentifier[0] != "notificationClass"
                    ):
                        self.COVSubscribe(
                            response.objectIdentifier, True, response.pduSource
                        )
            except Exception as e:
                logging.error(str(e) + " from " + str(iocb.ioResponse.pduSource) + "on read response")
                return False

    def on_WriteResult(self, iocb):
        """Response after writing to an object."""
        if iocb.ioError:
            logging.error(str(iocb.ioError) + " from " + str(iocb.ioError.pduSource) + " while writing")
            return

        if iocb.ioResponse:
            # should be a read property or read property multiple ack
            if not isinstance(iocb.ioResponse, SimpleAckPDU):
                logging.error(str(iocb.ioResponse.apduAbortRejectReason) + " from " + str(iocb.ioResponse.pduSource))
                return
            # Another read to update the dictionary value... CoV doesn't update every single thing.
            self.ReadProperty(
                iocb.args[0].objectIdentifier,
                iocb.args[0].propertyIdentifier,
                iocb.args[0].pduDestination,
            )

    def on_Subscribed(self, iocb):
        """Callback on whether subscribing was successful."""
        # do something for success
        if iocb.ioResponse:
            logging.info(
                "Subscribed to "
                + str(iocb.ioResponse.pduSource)
                + " object "
                + str(iocb.args[0].monitoredObjectIdentifier.value)
                + " with ID "
                + str(iocb.args[0].subscriberProcessIdentifier)
            )
            return

        # do something for error/reject/abort
        if iocb.ioError:
            logging.error(str(iocb.ioError) + " from " + str(iocb.ioError.pduSource) + "while subscribing")
            self.unassign_id(
                (
                    iocb.args[0].monitoredObjectIdentifier.value,
                    self.addr_to_dev_id(iocb.args[0].pduDestination),
                )
            )
