"""BACnet handler classes for BACnet add-on."""
import asyncio
import json
from math import isinf, isnan
from typing import Any, Dict, TypeVar

import backoff
import requests
import websockets
from bacpypes3.apdu import (AbortPDU, ConfirmedCOVNotificationRequest,
                            ErrorPDU, ErrorRejectAbortNack,
                            ReadPropertyRequest, RejectPDU, SimpleAckPDU,
                            SubscribeCOVRequest, WritePropertyRequest)
from bacpypes3.basetypes import (BinaryPV, DeviceStatus, EngineeringUnits,
                                 ErrorType, EventState, PropertyIdentifier,
                                 Reliability)
from bacpypes3.constructeddata import AnyAtomic
from bacpypes3.errors import *
from bacpypes3.ipv4.app import ForeignApplication, NormalApplication
from bacpypes3.local.analog import AnalogInputObject, AnalogValueObject
from bacpypes3.local.binary import BinaryInputObject, BinaryValueObject
from bacpypes3.object import CharacterStringValueObject, get_vendor_info
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier, ObjectType
from const import (LOGGER, device_properties_to_read,
                   object_properties_to_read_once,
                   object_properties_to_read_periodically)

KeyType = TypeVar("KeyType")


class BACnetIOHandler(NormalApplication, ForeignApplication):
    bacnet_device_dict: dict = {}
    subscription_tasks: list = []
    update_event: asyncio.Event = asyncio.Event()
    startup_complete: asyncio.Event = asyncio.Event()
    write_to_api: asyncio.Event = asyncio.Event()
    write_to_api_queue: asyncio.Queue = asyncio.Queue()
    id_to_object = {}
    object_to_id = {}
    available_ids = set()
    next_id = 1
    default_subscription_lifetime = 28800
    subscription_list = []

    def __init__(
        self, device, local_ip, foreign_ip="", ttl=255, update_event=asyncio.Event()
    ) -> None:
        if foreign_ip:
            ForeignApplication.__init__(self, device, local_ip)
            self.register(addr=Address(foreign_ip), ttl=int(ttl))
        else:
            NormalApplication.__init__(self, device, local_ip)
        super().i_am()
        super().who_is()
        self.update_event = update_event
        self.vendor_info = get_vendor_info(0)
        asyncio.get_event_loop().create_task(self.refresh_subscriptions())
        self.startup_complete.set()
        LOGGER.debug("Application initialised")

    def deep_update(
        self, mapping: Dict[KeyType, Any], *updating_mappings: Dict[KeyType, Any]
    ) -> Dict[KeyType, Any]:
        for updating_mapping in updating_mappings:
            for k, v in updating_mapping.items():
                if (
                    k in mapping
                    and isinstance(mapping[k], dict)
                    and isinstance(v, dict)
                ):
                    mapping[k] = self.deep_update(mapping[k], v)
                else:
                    mapping[k] = v
        self.update_event.set()
        # LOGGER.debug(f"Updating {updating_mapping}")
        return mapping

    def dev_to_addr(self, dev: ObjectIdentifier) -> Address | None:
        for instance in self.device_info_cache.instance_cache:
            if instance == dev[1]:
                return self.device_info_cache.instance_cache[instance].address
        return None

    def addr_to_dev(self, addr: Address) -> ObjectIdentifier | None:
        for address in self.device_info_cache.address_cache:
            if addr == address:
                return ObjectIdentifier(
                    f"device:{self.device_info_cache.address_cache[address].device_instance}"
                )
        return None

    def assign_id(self, obj: ObjectIdentifier, dev: ObjectIdentifier) -> int:
        """Assign an ID to the given object and return it."""
        if (obj, dev) in self.object_to_id:
            # The object already has an ID, return it
            return self.object_to_id[(obj, dev)]

        # Assign a new ID to the object
        if self.available_ids:
            # Use an available ID if there is one
            new_id = self.available_ids.pop()
        else:
            # Assign a new ID if there are no available IDs
            new_id = self.next_id
            self.next_id += 1

        self.id_to_object[new_id] = (obj, dev)
        self.object_to_id[(obj, dev)] = new_id
        return new_id

    def unassign_id(self, obj: ObjectIdentifier, dev: ObjectIdentifier) -> None:
        """Remove the ID assignment for the given object."""
        if (obj, dev) not in self.object_to_id:
            return

        # Remove the ID assignment for the object and add the ID to the available IDs set
        obj_id = self.object_to_id[(obj, dev)]
        del self.id_to_object[obj_id]
        del self.object_to_id[(obj, dev)]
        self.available_ids.add(obj_id)

    async def refresh_subscriptions(self):
        """Refreshing subscriptions automatically."""  # Maybe make a blacklist to exclude objects we dont want to subscribe to.
        while True:
            await asyncio.sleep(self.default_subscription_lifetime)
            LOGGER.info("Refreshing subscriptions...")
            for task in self.subscription_tasks:
                await self.create_subscription_task(
                    device_identifier=task[4],
                    object_identifier=task[1],
                    confirmed_notifications=task[2],
                    lifetime=task[3],
                )

    async def do_WhoIsRequest(self, apdu) -> None:
        """Handle incoming Who Is request."""
        LOGGER.info(f"Received Who Is Request from {apdu.pduSource}")
        await super().do_WhoIsRequest(apdu)

    async def do_IAmRequest(self, apdu) -> None:
        """Handle incoming I Am request."""

        LOGGER.info(f"I Am from {apdu.iAmDeviceIdentifier}")

        device_id = apdu.iAmDeviceIdentifier[1]

        if device_id in self.device_info_cache.instance_cache:
            LOGGER.debug(f"Device {apdu.iAmDeviceIdentifier} already in cache!")
            in_cache = True
        else:
            await self.device_info_cache.set_device_info(apdu)
            in_cache = False

        await super().do_IAmRequest(apdu)

        # if failed stop handling response
        if not await self.read_multiple_device_props(apdu=apdu):
            if self.bacnet_device_dict.get(f"device:{device_id}"):
                self.bacnet_device_dict.pop(f"device:{device_id}")
            return

        if not self.bacnet_device_dict.get(f"device:{device_id}"):
            LOGGER.error(f"Failed to get: {device_id}")
            return

        if not self.bacnet_device_dict[f"device:{device_id}"].get(
            f"device:{device_id}"
        ):
            LOGGER.error(f"Failed to get: {device_id}, {device_id}")
            return

        services_supported = self.bacnet_device_dict[f"device:{device_id}"][
            f"device:{device_id}"
        ].get("protocolServicesSupported")

        if services_supported["read-property-multiple"] == 1:
            await self.read_multiple_object_list(
                device_identifier=apdu.iAmDeviceIdentifier
            )
        else:
            await self.read_object_list(device_identifier=apdu.iAmDeviceIdentifier)

        await self.subscribe_object_list(device_identifier=apdu.iAmDeviceIdentifier)

    def dict_updater(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        property_identifier: PropertyIdentifier,
        property_value,
    ):
        if isinstance(property_value, ErrorType):
            return
        elif isinstance(property_value, float):
            if isnan(property_value):
                LOGGER.warning(
                    f"Ignoring property: {device_identifier}, {object_identifier}, {property_identifier}... NaN value: {property_value}"
                )
                property_value = 0
                return
            if isinf(property_value):
                LOGGER.warning(
                    f"Ignoring property: {device_identifier}, {object_identifier}, {property_identifier}... Inf value: {property_value}"
                )
                property_value = 0
                return
            property_value = round(property_value, 4)
        elif isinstance(property_value, AnyAtomic):
            return

        if isinstance(property_value, list):
            prop_list: list = []
            for val in property_value:
                if isinstance(val, ObjectIdentifier):
                    prop_list.append(
                        [
                            val[0].attr,
                            val[1],
                        ]
                    )
            pass

        if isinstance(property_value, ObjectIdentifier):
            self.deep_update(
                self.bacnet_device_dict,
                {
                    f"{device_identifier[0]}:{device_identifier[1]}": {
                        f"{object_identifier[0].attr}:{object_identifier[1]}": {
                            property_identifier.attr: (
                                property_value[0].attr,
                                property_value[1],
                            )
                        }
                    }
                },
            )
        elif isinstance(
            property_value,
            EventState | DeviceStatus | EngineeringUnits | Reliability | BinaryPV,
        ):
            self.deep_update(
                self.bacnet_device_dict,
                {
                    f"{device_identifier[0]}:{device_identifier[1]}": {
                        f"{object_identifier[0].attr}:{object_identifier[1]}": {
                            property_identifier.attr: property_value.attr,
                        }
                    }
                },
            )
        else:
            self.deep_update(
                self.bacnet_device_dict,
                {
                    f"{device_identifier[0]}:{device_identifier[1]}": {
                        f"{object_identifier[0].attr}:{object_identifier[1]}": {
                            property_identifier.attr: property_value
                        }
                    }
                },
            )

    async def read_multiple_device_props(self, apdu) -> bool:
        try:  # Send readPropertyMultiple and get response
            device_identifier = ObjectIdentifier(apdu.iAmDeviceIdentifier)
            parameter_list = [device_identifier, device_properties_to_read]

            LOGGER.debug(f"Exploring Device info of {device_identifier}")

            response = await self.read_property_multiple(
                address=apdu.pduSource, parameter_list=parameter_list
            )

        except AbortPDU as err:
            LOGGER.warning(
                f"Abort PDU error while reading device properties: {device_identifier}: {err}"
            )

            if "segmentation-not-supported" in str(err):
                return await self.read_device_props(apdu)
            elif "unrecognized-service" in str(err):
                return await self.read_device_props(apdu)
            elif "no-response" in str(err):
                return await self.read_device_props(apdu)
            else:
                return False

        except ErrorPDU as err:
            LOGGER.error(f"Error PDU reading device props: {device_identifier}: {err}")
            if "unrecognized-service" in str(err):
                await self.read_device_props(apdu)
                return False

        except ErrorRejectAbortNack as err:
            LOGGER.error(f"Nack error reading device props: {device_identifier}: {err}")
            if "unrecognized-service" in str(err):
                await self.read_device_props(apdu)

            return False

        except AttributeError as err:
            LOGGER.error(
                f"Attribute error reading device props: {device_identifier}: {err}"
            )
            return False
        else:
            for (
                object_identifier,
                property_identifier,
                property_array_index,
                property_value,
            ) in response:
                if property_value and property_value is not ErrorType:
                    self.dict_updater(
                        device_identifier=device_identifier,
                        object_identifier=object_identifier,
                        property_identifier=property_identifier,
                        property_value=property_value,
                    )
            return True

    async def read_device_props(self, apdu):
        address = apdu.pduSource
        device_identifier = apdu.iAmDeviceIdentifier

        for property_id in device_properties_to_read:
            if property_id == PropertyIdentifier("objectList"):
                continue

            try:
                response = await self.read_property(
                    address=address, objid=device_identifier, prop=property_id
                )

            except AbortPDU as err:
                LOGGER.error(
                    f"Abort PDU error while reading device properties one by one: {device_identifier}: {property_id} {err}"
                )
            except ErrorPDU as err:
                LOGGER.error(
                    f"Error PDU error reading device props one by one: {device_identifier}: {property_id} {err}"
                )
                continue
            except ErrorRejectAbortNack as err:
                LOGGER.error(
                    f"Nack error reading device props one by one: {device_identifier}: {property_id} {err}"
                )
            except AttributeError as err:
                LOGGER.error(
                    f"Attribute error reading device props one by one: {device_identifier}: {property_id} {err}"
                )
            except ValueError as err:
                LOGGER.error(
                    f"ValueError reading device props one by one: {device_identifier}: {property_id} {err}"
                )
            except Exception as err:
                LOGGER.error(
                    f"Exception reading device props one by one: {device_identifier}: {property_id} {err}"
                )
            else:
                if response is not ErrorType:
                    self.dict_updater(
                        device_identifier=device_identifier,
                        object_identifier=device_identifier,
                        property_identifier=property_id,
                        property_value=response,
                    )

        if not (await self.read_object_list_property(device_identifier)):
            return False
        return True

    async def read_object_list_property(self, device_identifier):
        """Read object list property in the smallest possible way."""
        address = self.dev_to_addr(dev=device_identifier)

        try:
            object_amount = await self.read_property(
                address=address,
                objid=device_identifier,
                prop=PropertyIdentifier("objectList"),
                array_index=0,
            )

        except Exception as err:
            LOGGER.warning(
                f"Error getting object list size for {device_identifier} at {address}"
            )
            return False

        object_list = []

        try:
            for number in range(1, object_amount + 1):
                object_type = await self.read_property(
                    address=address,
                    objid=device_identifier,
                    prop=PropertyIdentifier("objectList"),
                    array_index=number,
                )
                object_list.append(object_type)

            self.dict_updater(
                device_identifier=device_identifier,
                object_identifier=device_identifier,
                property_identifier=PropertyIdentifier("objectList"),
                property_value=object_list,
            )
        except Exception as err:
            LOGGER.warning(
                f"Error getting object list size for {device_identifier} at {address}"
            )
            return False
        return True

    async def read_multiple_object_list(self, device_identifier):
        """Read all objects from a device."""
        LOGGER.info(f"Reading objectList from {device_identifier}...")
        device_identifier = ObjectIdentifier(device_identifier)
        for obj_id in self.bacnet_device_dict[f"device:{device_identifier[1]}"][
            f"device:{device_identifier[1]}"
        ]["objectList"]:
            if not isinstance(obj_id, ObjectIdentifier):
                obj_id = ObjectIdentifier(obj_id)

            if (
                ObjectType(obj_id[0]) == ObjectType("device")
                or ObjectType(obj_id[0])
                not in self.vendor_info.registered_object_classes
            ):
                continue

            parameter_list = [obj_id, object_properties_to_read_once]

            try:  # Send readPropertyMultiple and get response
                LOGGER.debug(
                    f"Reading object {obj_id} of {device_identifier} during read_object_list"
                )

                response = await self.read_property_multiple(
                    address=self.dev_to_addr(device_identifier),
                    parameter_list=parameter_list,
                )
            except AbortPDU as err:
                LOGGER.warning(
                    f"Abort PDU Error while reading object list: {device_identifier}: {obj_id} {err}"
                )

                if not "segmentation-not-supported" in str(err):
                    return False
                else:
                    await self.read_object_list(device_identifier)

            except ErrorPDU as err:
                LOGGER.error(
                    f"Nack error while reading object list: {device_identifier}: {obj_id} {err}"
                )

                if "unrecognized-service" in str(err):
                    await self.read_object_list(device_identifier)

            except ErrorRejectAbortNack as err:
                LOGGER.error(
                    f"Nack error while reading object list: {device_identifier}: {obj_id} {err}"
                )

                if "unrecognized-service" in str(err):
                    await self.read_object_list(device_identifier)

            except AssertionError as err:
                LOGGER.error(
                    f"Assertion error for: {device_identifier}: {obj_id} {err}"
                )

            except AttributeError as err:
                LOGGER.error(
                    f"Attribute error while reading object list: {device_identifier}: {obj_id} {err}"
                )
            else:
                for (
                    object_identifier,
                    property_identifier,
                    property_array_index,
                    property_value,
                ) in response:
                    if property_value is not ErrorType:
                        self.dict_updater(
                            device_identifier=device_identifier,
                            object_identifier=object_identifier,
                            property_identifier=property_identifier,
                            property_value=property_value,
                        )

    async def read_object_list(self, device_identifier):
        try:
            for obj_id in self.bacnet_device_dict[f"device:{device_identifier[1]}"][
                f"device:{device_identifier[1]}"
            ]["objectList"]:
                if not isinstance(obj_id, ObjectIdentifier):
                    obj_id = ObjectIdentifier(obj_id)

                if (
                    ObjectType(obj_id[0]) == ObjectType("device")
                    or ObjectType(obj_id[0])
                    not in self.vendor_info.registered_object_classes
                ):
                    continue

                for property_id in object_properties_to_read_once:
                    try:
                        response = await self.read_property(
                            address=self.dev_to_addr(device_identifier),
                            objid=obj_id,
                            prop=property_id,
                        )
                    except AbortPDU as err:
                        LOGGER.error(
                            f"Abort PDU while reading device object list one by one: {device_identifier} {obj_id} {property_id}: {err}"
                        )
                    except ErrorPDU as err:
                        LOGGER.error(
                            f"Error PDU reading object list one by one: {device_identifier} {obj_id} {property_id}: {err}"
                        )
                        continue
                    except ErrorRejectAbortNack as err:
                        LOGGER.error(
                            f"Nack error reading object list one by one: {device_identifier} {obj_id} {property_id}: {err}"
                        )
                        continue
                    else:
                        if response is not ErrorType:
                            self.dict_updater(
                                device_identifier=device_identifier,
                                object_identifier=obj_id,
                                property_identifier=property_id,
                                property_value=response,
                            )

        except AttributeError as err:
            LOGGER.error(
                f"Attribute error reading object list one by one: {device_identifier}: {err}"
            )

    async def read_multiple_objects_periodically(self, device_identifier):
        """Read objects after a set time."""
        LOGGER.info(f"Periodic object reading...")

        for obj_id in self.bacnet_device_dict[device_identifier]:
            if not isinstance(obj_id, ObjectIdentifier):
                obj_id = ObjectIdentifier(obj_id)
                device_identifier = ObjectIdentifier(device_identifier)

            if (
                ObjectType(obj_id[0]) == ObjectType("device")
                or ObjectType(obj_id[0])
                not in self.vendor_info.registered_object_classes
            ):
                continue

            parameter_list = [obj_id, object_properties_to_read_periodically]

            try:  # Send readPropertyMultiple and get response
                LOGGER.debug(
                    f"Reading object {obj_id} of {device_identifier} during read_objects_periodically"
                )

                response = await self.read_property_multiple(
                    address=self.dev_to_addr(ObjectIdentifier(device_identifier)),
                    parameter_list=parameter_list,
                )
            except AbortPDU as err:
                LOGGER.warning(f"Abort PDU Error: {obj_id}: {err}")

                if not "segmentation-not-supported" in str(err):
                    return False
                else:
                    await self.read_objects_periodically(device_identifier)

            except ErrorPDU as err:
                LOGGER.error(f"Error PDU reading objects periodically: {obj_id}: {err}")
                if "unrecognized-service" in str(err):
                    await self.read_objects_periodically(device_identifier)

            except ErrorRejectAbortNack as err:
                LOGGER.error(
                    f"Nack error reading objects periodically: {obj_id}: {err}"
                )
                if "unrecognized-service" in str(err):
                    await self.read_objects_periodically(device_identifier)

            except AttributeError as err:
                LOGGER.error(f"Attribute error: {obj_id}: {err}")

            else:
                for (
                    object_identifier,
                    property_identifier,
                    property_array_index,
                    property_value,
                ) in response:
                    if property_value is not ErrorType:
                        self.dict_updater(
                            device_identifier=device_identifier,
                            object_identifier=object_identifier,
                            property_identifier=property_identifier,
                            property_value=property_value,
                        )

    async def read_objects_periodically(self, device_identifier):
        """Read objects if regular way failed."""
        LOGGER.info(f"Reading objects non segmented for {device_identifier}...")
        for obj_id in self.bacnet_device_dict[device_identifier]:
            if not isinstance(obj_id, ObjectIdentifier):
                obj_id = ObjectIdentifier(obj_id)
                device_identifier = ObjectIdentifier(device_identifier)

            if (
                ObjectType(obj_id[0]) == ObjectType("device")
                or ObjectType(obj_id[0])
                not in self.vendor_info.registered_object_classes
            ):
                continue

            for property_id in object_properties_to_read_periodically:
                try:
                    response = await self.read_property(
                        address=self.dev_to_addr(device_identifier),
                        objid=obj_id,
                        prop=property_id,
                    )
                except AbortPDU as err:
                    LOGGER.error(
                        f"Abort PDU Errorreading objects one by one periodically: {obj_id}: {err}"
                    )

                except ErrorPDU as err:
                    LOGGER.error(
                        f"Error PDU reading objects one by one periodically: {device_identifier} {obj_id} {property_id}: {err}"
                    )
                    continue

                except ErrorRejectAbortNack as err:
                    LOGGER.error(
                        f"Nack error reading objects one by one periodically: {device_identifier} {obj_id} {property_id}: {err}"
                    )
                    continue
                except AttributeError as err:
                    LOGGER.error(f"Attribute error: {obj_id}: {err}")
                else:
                    if response is not ErrorType:
                        self.dict_updater(
                            device_identifier=device_identifier,
                            object_identifier=obj_id,
                            property_identifier=property_id,
                            property_value=response,
                        )

    async def subscribe_object_list(self, device_identifier):
        """ "Subscribe to selected objects."""  # Maybe make a blacklist to exclude objects we dont want to subscribe to.
        for object_id in self.bacnet_device_dict[f"device:{device_identifier[1]}"]:
            if ObjectIdentifier(object_id)[0] in self.subscription_list:
                await self.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=ObjectIdentifier(object_id),
                    confirmed_notifications=True,
                    lifetime=self.default_subscription_lifetime,
                )

    async def create_subscription_task(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        confirmed_notifications: bool,
        lifetime: int | None = None,
    ):
        """Actually creating and sending a subscription."""

        if isinstance(object_identifier, str):
            object_identifier = ObjectIdentifier(object_identifier)

        if isinstance(device_identifier, str):
            device_identifier = ObjectIdentifier(device_identifier)

        subscriber_process_identifier = self.assign_id(
            dev=device_identifier, obj=object_identifier
        )

        subscribe_req = SubscribeCOVRequest(
            subscriberProcessIdentifier=subscriber_process_identifier,
            monitoredObjectIdentifier=object_identifier,
            issueConfirmedNotifications=confirmed_notifications,
            lifetime=lifetime,
            destination=self.dev_to_addr(ObjectIdentifier(device_identifier)),
        )

        try:
            response = await self.request(subscribe_req)
            LOGGER.info(
                f"Subscribing to: {device_identifier}, {object_identifier}... response: {response}"
            )

        except (ErrorRejectAbortNack, RejectException, AbortException) as error:
            LOGGER.error(
                f"Error while subscribing to {device_identifier}, {object_identifier}: {error}"
            )
            return
        except (AbortPDU, ErrorPDU, RejectPDU) as error:
            LOGGER.error(
                f"Error while subscribing to {device_identifier}, {object_identifier}: {error}"
            )
            return

        if (
            not [
                subscriber_process_identifier,
                object_identifier,
                confirmed_notifications,
                lifetime,
                ObjectIdentifier(device_identifier),
            ]
            in self.subscription_tasks
        ):
            self.subscription_tasks.append(
                [
                    subscriber_process_identifier,
                    object_identifier,
                    confirmed_notifications,
                    lifetime,
                    ObjectIdentifier(device_identifier),
                ]
            )

    async def unsubscribe_COV(
        self, subscriber_process_identifier, device_identifier, object_identifier
    ):
        """Unsubscribe from an object."""
        unsubscribe_cov_request = SubscribeCOVRequest(
            subscriberProcessIdentifier=subscriber_process_identifier,
            monitoredObjectIdentifier=object_identifier,
        )
        unsubscribe_cov_request.pduDestination = self.dev_to_addr(device_identifier)
        # send the request, wait for the response
        response = await self.request(unsubscribe_cov_request)

        if not isinstance(response, SimpleAckPDU):
            return False

        for subscription in self.subscription_tasks:
            if (
                subscription[0] == subscriber_process_identifier
                and subscription[1] == object_identifier
                and subscription[4] == device_identifier
            ):
                self.unassign_id(obj=subscription[1], dev=subscription[4])
                del self.subscription_tasks[self.subscription_tasks.index(subscription)]
                return

    async def end_subscription_tasks(self):
        while self.subscription_tasks:
            for subscription in self.subscription_tasks:
                await self.unsubscribe_COV(
                    subscriber_process_identifier=subscription[0],
                    device_identifier=subscription[4],
                    object_identifier=subscription[1],
                )

    async def do_ConfirmedCOVNotificationRequest(
        self, apdu: ConfirmedCOVNotificationRequest
    ) -> None:
        # await super().do_ConfirmedCOVNotificationRequest(apdu)

        try:
            for value in apdu.listOfValues:
                vendor_info = get_vendor_info(0)
                object_class = vendor_info.get_object_class(
                    apdu.monitoredObjectIdentifier[0]
                )
                property_type = object_class.get_property_type(value.propertyIdentifier)

                if property_type == None:
                    LOGGER.warning(
                        f"NoneType property: {apdu.monitoredObjectIdentifier[0]} {value.propertyIdentifier} {value.value}"
                    )
                    continue
                elif value.propertyIdentifier not in object_properties_to_read_once:
                    LOGGER.warning(
                        f"Ignoring property: {apdu.monitoredObjectIdentifier[0]} {value.propertyIdentifier} {value.value}"
                    )
                    continue
                else:
                    property_value = value.value.cast_out(property_type)

                LOGGER.debug(
                    f"COV: {apdu.initiatingDeviceIdentifier}, {apdu.monitoredObjectIdentifier}, {value.propertyIdentifier}, {property_value}"
                )

                self.dict_updater(
                    device_identifier=apdu.initiatingDeviceIdentifier,
                    object_identifier=apdu.monitoredObjectIdentifier,
                    property_identifier=value.propertyIdentifier,
                    property_value=property_value,
                )

        except Exception as err:
            LOGGER.error(
                f"{apdu.monitoredObjectIdentifier[0]}: {apdu.listOfValues} + {err}"
            )

        # success
        resp = SimpleAckPDU(context=apdu)

        # return the result
        await self.response(resp)

    async def do_ReadPropertyRequest(self, apdu: ReadPropertyRequest) -> None:
        try:
            await super().do_ReadPropertyRequest(apdu)
        except (Exception, AttributeError) as err:
            await super().do_ReadPropertyRequest(apdu)
            LOGGER.warning(
                f"{self.addr_to_dev(apdu.pduSource)} tried to read {apdu.objectIdentifier} {apdu.propertyIdentifier}: {err}"
            )

    async def do_WritePropertyRequest(self, apdu: WritePropertyRequest):
        try:
            obj_id = apdu.objectIdentifier

            obj = self.get_object_id(obj_id)

            if not obj:
                raise ExecutionError(errorClass="object", errorCode="unknownObject")

            property_type = obj.get_property_type(apdu.propertyIdentifier)

            array_index = apdu.propertyArrayIndex

            priority = apdu.priority

            property_value = apdu.propertyValue.cast_out(
                property_type, null=(priority is not None)
            )

            obj_out_of_service = getattr(obj, "outOfService", None)

            if (
                apdu.propertyIdentifier == PropertyIdentifier("presentValue")
                and not obj_out_of_service
            ):
                await self.write_to_api_queue.put(
                    (obj_id, property_type, array_index, priority, property_value)
                )

                self.write_to_api.set()

                while self.write_to_api.is_set():
                    await asyncio.sleep(0.1)

                response = await self.write_to_api_queue.get()

                if not response:
                    # Reject
                    resp = RejectPDU(context=apdu, reason=0)

                    # return the result
                    await self.response(resp)

                    LOGGER.info(
                        f"Rejected write for {apdu.objectIdentifier} {apdu.propertyIdentifier}!"
                    )

                else:
                    # Acknowledge
                    resp = SimpleAckPDU(context=apdu)

                    # return the result
                    await self.response(resp)

                    LOGGER.info(
                        f"Ack'd write for {apdu.objectIdentifier} {apdu.propertyIdentifier}!"
                    )

            elif (
                (
                    apdu.propertyIdentifier == PropertyIdentifier("presentValue")
                    and obj_out_of_service
                )
                or (apdu.propertyIdentifier == PropertyIdentifier("covIncrement"))
                or (apdu.propertyIdentifier == PropertyIdentifier("outOfService"))
            ):
                await obj.write_property(
                    apdu.propertyIdentifier, property_value, array_index, priority
                )

                # success
                resp = SimpleAckPDU(context=apdu)

                # return the result
                await self.response(resp)

                LOGGER.info(
                    f"Ack'd' write for {apdu.objectIdentifier} {apdu.propertyIdentifier}!"
                )

            else:
                resp = RejectPDU(context=apdu, reason=0)

                # return the result
                await self.response(resp)

                LOGGER.warning(
                    f"Rejected write for {apdu.objectIdentifier} {apdu.propertyIdentifier}!"
                )

        except Exception as err:
            LOGGER.exception(
                f"Something went wrong while getting object written! {apdu.pduSource}"
            )


class ObjectManager:
    """Manages BACpypes3 application objects."""

    binary_val_entity_ids = []
    binary_in_entity_ids = []
    analog_val_entity_ids = []
    analog_in_entity_ids = []
    multi_state_val_entity_ids = []
    multi_state_in_entity_ids = []
    char_string_val_entity_ids = []
    services = {}

    def __init__(self, app: BACnetIOHandler, api_token: str, entity_list: list = None):
        """Initialize objects."""
        self.app = app
        self.api_token = api_token
        self.entity_list = entity_list

        if not self.api_token:
            return None

        self.services = self.fetch_services()

        if not self.entity_list:
            return None

        self.process_entity_list(entity_list=entity_list)

        for index, entity in enumerate(self.binary_val_entity_ids):
            data = self.fetch_entity_data(entity)
            self.add_object(object_type="binaryValue", index=index, entity=data)

        for index, entity in enumerate(self.binary_in_entity_ids):
            data = self.fetch_entity_data(entity)
            self.add_object(object_type="binaryInput", index=index, entity=data)

        for index, entity in enumerate(self.analog_val_entity_ids):
            data = self.fetch_entity_data(entity)
            self.add_object(object_type="analogValue", index=index, entity=data)

        for index, entity in enumerate(self.analog_in_entity_ids):
            data = self.fetch_entity_data(entity)
            self.add_object(object_type="analogInput", index=index, entity=data)

        for index, entity in enumerate(self.char_string_val_entity_ids):
            data = self.fetch_entity_data(entity)
            self.add_object(
                object_type="characterstringValue", index=index, entity=data
            )

        asyncio.create_task(self.data_websocket_task())

        asyncio.create_task(self.data_write_task())

    @backoff.on_exception(backoff.expo, Exception, max_time=60)
    def process_entity_list(self, entity_list: list) -> None:
        """Fill bacnet object list"""
        self.binary_val_entity_ids = []
        self.binary_in_entity_ids = []
        self.analog_val_entity_ids = []
        self.analog_in_entity_ids = []
        self.multi_state_val_entity_ids = []
        self.multi_state_in_entity_ids = []
        self.char_string_val_entity_ids = []

        for entity in entity_list:
            split_entity = entity.split(".")

            if split_entity[0] in ("number", "input_number", "counter"):  # analog val
                self.analog_val_entity_ids.append(entity)

            elif split_entity[0] in (
                "sensor"
            ):  # analog in of character string val wanneer string
                data = self.fetch_entity_data(entity)

                state = data.get("state")

                try:
                    state = float(state)
                except ValueError:
                    LOGGER.debug(f"state {state} is not a number")

                if isinstance(state, (int, float, complex)):
                    self.analog_in_entity_ids.append(entity)
                elif (state == "unavailable" or state == "unknown") and data[
                    "attributes"
                ].get("unit_of_measurement"):
                    LOGGER.warning(
                        f"Assuming {entity} is analogInput as it's currently unavailable and has units!'"
                    )
                    self.analog_in_entity_ids.append(entity)
                else:
                    self.char_string_val_entity_ids.append(entity)

            # elif split_entity[0] in ("climate"): # multistate value, analog val voor set, analog in voor temperatuur
            # 	self.multi_state_val_entity_ids.append(entity) state
            # 	self.analog_val_entity_ids.append(entity) setpoint
            # 	self.analog_in_entity_ids.append(entity) temp

            # elif split_entity[0] in ("water_heater"): # character string en analog input voor temp
            # 	self.char_string_val_entity_ids.append(entity) state
            # 	self.analog_in_entity_ids.append(entity) temp

            elif split_entity[0] in (
                "switch",
                "input_boolean",
                "light",
            ):  # binary value
                self.binary_val_entity_ids.append(entity)

            elif split_entity[0] in ("binary_sensor", "schedule"):  # binary in
                self.binary_in_entity_ids.append(entity)

            # elif split_entity[0] in ("media_player", "vacuum"): # multistate in
            # 	self.multi_state_in_entity_ids.append(entity) state

            else:
                LOGGER.warning(
                    f"Entity {entity} can't be turned into an object as it's not supported!"
                )

    def entity_to_obj(self, entity):
        if entity in self.binary_val_entity_ids:
            object_type = "binaryValue"
            index = self.binary_val_entity_ids.index(entity)
        elif entity in self.binary_in_entity_ids:
            object_type = "binaryInput"
            index = self.binary_in_entity_ids.index(entity)
        elif entity in self.analog_val_entity_ids:
            object_type = "analogValue"
            index = self.analog_val_entity_ids.index(entity)
        elif entity in self.analog_in_entity_ids:
            object_type = "analogInput"
            index = self.analog_in_entity_ids.index(entity)
        elif entity in self.char_string_val_entity_ids:
            object_type = "characterstringValue"
            index = self.char_string_val_entity_ids.index(entity)

        return self.app.get_object_id(
            ObjectIdentifier(str(object_type + ":" + str(index)))
        )

    def fetch_entity_data(self, entity_id):
        """Fetch data from API."""
        url = f"http://supervisor/core/api/states/{entity_id}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "content-type": "application/json",
        }

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return json.loads(response.text)
        else:
            LOGGER.error(f"Failed to get {entity_id}. {response.status_code}")
            return False

    def fetch_services(self):
        """Fetch data from API."""
        url = f"http://supervisor/core/api/services"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "content-type": "application/json",
        }

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return json.loads(response.text)
        else:
            LOGGER.error(f"Failed to get services. {response.status_code}")
            return False

    def post_services(self, entity_id, value):
        """Write value to API."""

        split_id = entity_id.split(".")

        domain = split_id[0]

        data = {"entity_id": f"{entity_id}"}

        if domain in ("number", "input_number", "counter"):
            service = "set_value"
            data.update({"value": value})
        elif domain in (
            "switch",
            "light",
            "camera",
            "climate",
            "water_heater",
            "media_player",
            "input_boolean",
        ):
            service = "turn_on" if value else "turn_off"
        else:
            LOGGER.error(f"Can not write to {entity_id} as it's deemed not writable'")
            return False

        url = f"http://supervisor/core/api/services/{domain}/{service}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "content-type": "application/json",
        }

        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            return True
        else:
            LOGGER.error(
                f"Failed to post {entity_id}: HTTP Code {response.status_code}"
            )
            return False

    def add_object(self, object_type: str, index: int, entity: dict):
        """Add object to application"""

        friendly_name = entity["attributes"].get("friendly_name")

        description = f"Home Assistant entity {friendly_name}"

        if object_type == "binaryValue":
            bin_val_obj = BinaryValueObject(
                objectIdentifier=f"{object_type},{index}",
                objectName=entity["attributes"].get("friendly_name"),
                presentValue=True if entity.get("state").lower() == "on" else False,
                description=description,
                eventState=EventState.normal,
                outOfService=False,
            )
            self.app.add_object(bin_val_obj)

        elif object_type == "binaryInput":
            bin_val_obj = BinaryInputObject(
                objectIdentifier=f"{object_type},{index}",
                objectName=entity["attributes"].get("friendly_name"),
                presentValue=True if entity.get("state").lower() == "on" else False,
                description=description,
                eventState=EventState.normal,
                outOfService=False,
            )
            self.app.add_object(bin_val_obj)

        elif object_type == "analogValue":
            units = (
                self.determine_units(entity["attributes"].get("unit_of_measurement"))
                if entity["attributes"].get("unit_of_measurement") is not None
                else None
            )

            pres_val = entity.get("state")

            if pres_val == "unavailable":
                pres_val = int(0)
                event_state = EventState.offnormal
            else:
                event_state = EventState.normal

            ana_val_obj = AnalogValueObject(
                objectIdentifier=f"{object_type},{index}",
                objectName=entity["attributes"].get("friendly_name"),
                presentValue=pres_val,
                description=description,
                eventState=event_state,
                outOfService=False,
                covIncrement=0.1,
                units=units,
            )
            self.app.add_object(ana_val_obj)

        elif object_type == "analogInput":
            units = (
                self.determine_units(entity["attributes"].get("unit_of_measurement"))
                if entity["attributes"].get("unit_of_measurement") is not None
                else None
            )

            pres_val = entity.get("state")

            if pres_val == "unavailable":
                pres_val = int(0)
                event_state = EventState.offnormal
            else:
                event_state = EventState.normal

            ana_in_obj = AnalogInputObject(
                objectIdentifier=f"{object_type},{index}",
                objectName=entity["attributes"].get("friendly_name"),
                presentValue=pres_val,
                description=description,
                eventState=event_state,
                outOfService=False,
                covIncrement=0.1,
                units=units,
            )
            self.app.add_object(ana_in_obj)

        elif object_type == "characterstringValue":
            char_val_obj = CharacterStringValueObject(
                objectIdentifier=f"{object_type},{index}",
                objectName=entity["attributes"].get("friendly_name"),
                presentValue=entity.get("state"),
                description=description,
                eventState=EventState.normal,
                outOfService=False,
            )
            self.app.add_object(char_val_obj)

    def determine_units(self, unit):
        """EngineeringUnits for objects from Home Assistant units"""

        if not unit:
            return None

        if "C" in unit and len(unit) == 2:
            bacnetUnits = EngineeringUnits("degreesCelsius")
        elif "F" in unit and len(unit) == 2:
            bacnetUnits = EngineeringUnits("degreesFahrenheit")
        elif "K" in unit and len(unit) == 2:
            bacnetUnits = EngineeringUnits("degreesKelvin")
        elif unit == "%":
            bacnetUnits = EngineeringUnits("percent")
        elif unit == "bar":
            bacnetUnits = EngineeringUnits(55)
        elif unit == "kWh":
            bacnetUnits = EngineeringUnits("kilowattHours")
        elif unit == "W":
            bacnetUnits = EngineeringUnits("watts")
        elif unit == "km/h":
            bacnetUnits = EngineeringUnits("kilometersPerHour")
        elif unit == "m/s":
            bacnetUnits = EngineeringUnits("metersPerSecond")
        elif unit == "mph":
            bacnetUnits = EngineeringUnits("milesPerHour")
        elif unit == "ft/s":
            bacnetUnits = EngineeringUnits("feetPerSecond")
        elif unit == "\u0057\u002f\u006d\u00b2":
            bacnetUnits = EngineeringUnits("wattsPerSquareMeter")
        elif unit == "lx":
            bacnetUnits = EngineeringUnits("luxes")
        else:
            bacnetUnits = None
        return bacnetUnits

    def update_object(self, object_type, index, entity):
        """Update objects with API data."""

        LOGGER.debug(f"UPDATING {object_type} {index} {entity}")

        obj = self.app.get_object_id(
            ObjectIdentifier(str(object_type + ":" + str(index)))
        )

        pres_val = entity.get("state")

        if pres_val == "unavailable":
            setattr(obj, "eventState", EventState.offnormal)
            return
        else:
            setattr(obj, "eventState", EventState.normal)

        if object_type == "binaryValue" or object_type == "binaryInput":
            value = True if pres_val.lower() == "on" else False

        elif (
            object_type == "analogValue"
            or object_type == "analogInput"
            or object_type == "characterstringValue"
        ):
            value = pres_val

        setattr(obj, "presentValue", value)

    async def data_websocket_task(self):
        auth = {"type": "auth", "access_token": f"{self.api_token}"}

        message_id = 1

        async for websocket in websockets.connect("ws://supervisor/core/api/websocket"):
            try:
                data = json.loads(await websocket.recv())
                await websocket.send(json.dumps(auth))
                data = json.loads(await websocket.recv())
                if data.get("type") != "auth_ok":
                    LOGGER.error("Authentication with API failed!")
                    continue

                subscribe_to_state = {
                    "id": message_id,
                    "type": "subscribe_trigger",
                    "trigger": {
                        "platform": "state",
                        "entity_id": self.entity_list,
                    },
                }

                await websocket.send(json.dumps(subscribe_to_state))
                data = json.loads(await websocket.recv())
                if data.get("success"):
                    LOGGER.debug(f"Subscribed to selected entities!")
                    message_id = message_id + 1

                while True:
                    data = json.loads(await websocket.recv())
                    LOGGER.debug(f"Received: {str(data)}")

                    new_state = data["event"]["variables"]["trigger"]["to_state"]

                    entity_id = new_state.get("entity_id")

                    if entity_id in self.binary_val_entity_ids:
                        object_type = "binaryValue"
                        index = self.binary_val_entity_ids.index(entity_id)
                    elif entity_id in self.binary_in_entity_ids:
                        object_type = "binaryInput"
                        index = self.binary_in_entity_ids.index(entity_id)
                    elif entity_id in self.analog_val_entity_ids:
                        object_type = "analogValue"
                        index = self.analog_val_entity_ids.index(entity_id)
                    elif entity_id in self.analog_in_entity_ids:
                        object_type = "analogInput"
                        index = self.analog_in_entity_ids.index(entity_id)
                    elif entity_id in self.char_string_val_entity_ids:
                        object_type = "characterstringValue"
                        index = self.char_string_val_entity_ids.index(entity_id)
                    else:
                        continue

                    obj = self.entity_to_obj(entity=entity_id)
                    if getattr(obj, "outOfService", None):
                        continue

                    self.update_object(
                        object_type=object_type, index=index, entity=new_state
                    )

            except websockets.ConnectionClosed as err:
                LOGGER.warning(
                    f"Websocket connection to Home Assistant API closed! Attempting to reconnect..."
                )
                continue
            except Exception as err:
                LOGGER.error(
                    f"Websocket connection to Home Assistant API failed! {err}"
                )

    async def data_write_task(self):
        """Updater task to write data to Home Assistant."""
        try:
            while True:
                await self.app.write_to_api.wait()

                (
                    obj,
                    property_type,
                    array_index,
                    priority,
                    property_value,
                ) = await self.app.write_to_api_queue.get()

                entity_index = obj[1]

                if obj[0].attr == "binaryValue":
                    entity_id = self.binary_val_entity_ids[entity_index]
                elif obj[0].attr == "analogValue":
                    entity_id = self.analog_val_entity_ids[entity_index]
                else:
                    entity_id = None

                write_response = self.post_services(
                    entity_id=entity_id, value=property_value
                )

                self.app.write_to_api.clear()

                data = self.fetch_entity_data(entity_id)

                self.update_object(
                    object_type=obj[0].attr, index=entity_index, entity=data
                )

                if write_response:
                    await self.app.write_to_api_queue.put(True)
                else:
                    await self.app.write_to_api_queue.put(False)

        except asyncio.CancelledError as err:
            LOGGER.warning(f"data_update_task cancelled: {err}")
