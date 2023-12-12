import asyncio
import logging
import traceback
from math import isinf, isnan
from typing import Any, Dict, TypeVar

from bacpypes3.apdu import (AbortPDU, ConfirmedCOVNotificationRequest,
                            ErrorPDU, ErrorRejectAbortNack,
                            ReadPropertyRequest, RejectPDU, SimpleAckPDU,
                            SubscribeCOVRequest)
from bacpypes3.basetypes import (BinaryPV, DeviceStatus, EngineeringUnits,
                                 ErrorType, EventState, PropertyIdentifier,
                                 Reliability)
from bacpypes3.constructeddata import AnyAtomic
from bacpypes3.errors import *
from bacpypes3.ipv4.app import ForeignApplication, NormalApplication
from bacpypes3.object import get_vendor_info
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import BitString, ObjectIdentifier, ObjectType
from const import (device_properties_to_read, object_properties_to_read_once,
                   object_properties_to_read_periodically)

KeyType = TypeVar("KeyType")


class BACnetIOHandler(NormalApplication, ForeignApplication):
    bacnet_device_dict: dict = {}
    subscription_tasks: list = []
    update_event: asyncio.Event = asyncio.Event()
    startup_complete: asyncio.Event = asyncio.Event()
    id_to_object = {}
    object_to_id = {}
    available_ids = set()
    next_id = 1
    default_subscription_lifetime = 28800
    subscription_list = []

    def __init__(self, device, local_ip, foreign_ip="", ttl=255) -> None:
        if foreign_ip:
            ForeignApplication.__init__(self, device, local_ip)
            self.register(addr=foreign_ip, ttl=60)
        else:
            NormalApplication.__init__(self, device, local_ip)
        super().i_am()
        super().who_is()
        self.vendor_info = get_vendor_info(0)
        asyncio.get_event_loop().create_task(self.refresh_subscriptions())
        self.startup_complete.set()
        logging.debug("Application initialised")

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
        # logging.debug(f"Updating {updating_mapping}")
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
        while True:
            logging.info("Refreshing subscriptions...")
            await asyncio.sleep(self.default_subscription_lifetime)
            for task in self.subscription_tasks:
                await self.create_subscription_task(
                    device_identifier=task[4],
                    object_identifier=task[1],
                    confirmed_notifications=task[2],
                    lifetime=task[3],
                )

    async def do_WhoIsRequest(self, apdu) -> None:
        logging.info(f"Received Who Is Request from {apdu.pduSource}")
        await super().do_WhoIsRequest(apdu)

    async def do_IAmRequest(self, apdu) -> None:
        logging.info(f"I Am from {apdu.iAmDeviceIdentifier}")

        if apdu.iAmDeviceIdentifier[1] in self.device_info_cache.instance_cache:
            logging.debug(f"Device {apdu.iAmDeviceIdentifier} already in cache!")

        await super().do_IAmRequest(apdu)

        await self.read_device_props(apdu=apdu)

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
                logging.warning(
                    f"Replacing with 0: {device_identifier}, {object_identifier}, {property_identifier}... NaN value: {property_value}"
                )
                property_value = 0
            if isinf(property_value):
                logging.warning(
                    f"Replacing with 0: {device_identifier}, {object_identifier}, {property_identifier}... Inf value: {property_value}"
                )
                property_value = 0
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

    async def read_device_props(self, apdu) -> bool:
        try:  # Send readPropertyMultiple and get response
            device_identifier = ObjectIdentifier(apdu.iAmDeviceIdentifier)
            parameter_list = [device_identifier, device_properties_to_read]

            logging.debug(f"Exploring Device info of {device_identifier}")

            response = await self.read_property_multiple(
                address=apdu.pduSource, parameter_list=parameter_list
            )

        except AbortPDU as err:
            logging.error(
                f"Abort PDU error while reading device properties: {device_identifier}: {err}"
            )

        except ErrorRejectAbortNack as err:
            logging.error(f"Nack error: {device_identifier}: {err}")
        except AttributeError as err:
            logging.error(f"Attribute error: {err}")
        else:
            for (
                object_identifier,
                property_identifier,
                property_array_index,
                property_value,
            ) in response:
                self.dict_updater(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    property_identifier=property_identifier,
                    property_value=property_value,
                )

    async def read_object_list(self, device_identifier):
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
                logging.debug(
                    f"Reading object {obj_id} of {device_identifier} during read_object_list"
                )

                response = await self.read_property_multiple(
                    address=self.dev_to_addr(device_identifier),
                    parameter_list=parameter_list,
                )
            except AbortPDU as err:
                logging.error(
                    f"Abort PDU Error while reading object list: {obj_id}: {err}"
                )

            except ErrorRejectAbortNack as err:
                logging.error(f"Nack error while reading object list: {obj_id}: {err}")

            except AssertionError as err:
                logging.error(f"Assertion error for: {device_identifier}: {obj_id}")

            except AttributeError as err:
                logging.error(
                    f"Attribute error while reading object list: {obj_id}: {err}"
                )
            else:
                for (
                    object_identifier,
                    property_identifier,
                    property_array_index,
                    property_value,
                ) in response:
                    self.dict_updater(
                        device_identifier=device_identifier,
                        object_identifier=object_identifier,
                        property_identifier=property_identifier,
                        property_value=property_value,
                    )

    async def read_objects_periodically(self):
        logging.debug(f"Periodic object reading...")
        for dev_id in self.bacnet_device_dict:
            for obj_id in self.bacnet_device_dict[dev_id]:
                if not isinstance(obj_id, ObjectIdentifier):
                    obj_id = ObjectIdentifier(obj_id)
                    device_identifier = ObjectIdentifier(dev_id)

                if (
                    ObjectType(obj_id[0]) == ObjectType("device")
                    or ObjectType(obj_id[0])
                    not in self.vendor_info.registered_object_classes
                ):
                    continue

                parameter_list = [obj_id, object_properties_to_read_periodically]

                try:  # Send readPropertyMultiple and get response
                    logging.debug(
                        f"Reading object {obj_id} of {device_identifier} during read_objects_periodically"
                    )

                    response = await self.read_property_multiple(
                        address=self.dev_to_addr(ObjectIdentifier(dev_id)),
                        parameter_list=parameter_list,
                    )
                except AbortPDU as err:
                    logging.error(f"Abort PDU Error: {obj_id}: {err}")

                except ErrorRejectAbortNack as err:
                    logging.error(f"Nack error: {obj_id}: {err}")

                except AttributeError as err:
                    logging.error(f"Attribute error: {obj_id}: {err}")

                else:
                    for (
                        object_identifier,
                        property_identifier,
                        property_array_index,
                        property_value,
                    ) in response:
                        self.dict_updater(
                            device_identifier=device_identifier,
                            object_identifier=object_identifier,
                            property_identifier=property_identifier,
                            property_value=property_value,
                        )

    async def subscribe_object_list(self, device_identifier):
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
            logging.debug(response)

        except (ErrorRejectAbortNack, RejectException, AbortException) as error:
            logging.error(
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

        for value in apdu.listOfValues:
            vendor_info = get_vendor_info(0)
            object_class = vendor_info.get_object_class(
                apdu.monitoredObjectIdentifier[0]
            )
            property_type = object_class.get_property_type(value.propertyIdentifier)
            property_value = value.value.cast_out(property_type)

            self.dict_updater(
                device_identifier=apdu.initiatingDeviceIdentifier,
                object_identifier=apdu.monitoredObjectIdentifier,
                property_identifier=value.propertyIdentifier,
                property_value=property_value,
            )

        # success
        resp = SimpleAckPDU(context=apdu)

        # return the result
        await self.response(resp)

    async def do_ReadPropertyRequest(self, apdu: ReadPropertyRequest) -> None:
        try:
            await super().do_ReadPropertyRequest(apdu)
        except (Exception, AttributeError) as err:
            logging.error(
                f"{self.addr_to_dev(apdu.pduSource)} tried to read {apdu.objectIdentifier} {apdu.propertyIdentifier}: {err}"
            )
