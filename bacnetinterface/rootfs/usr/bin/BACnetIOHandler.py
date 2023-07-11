import asyncio
import logging
import traceback
from typing import Any, Dict, TypeVar

from bacpypes3.apdu import (AbortPDU, ConfirmedCOVNotificationRequest,
                            ErrorPDU, ErrorRejectAbortNack,
                            ReadPropertyRequest, SubscribeCOVRequest)
from bacpypes3.basetypes import (BinaryPV, DeviceStatus, EngineeringUnits,
                                 ErrorType, EventState, PropertyIdentifier,
                                 Reliability)
from bacpypes3.constructeddata import AnyAtomic
from bacpypes3.errors import *
from bacpypes3.ipv4.app import NormalApplication
from bacpypes3.object import get_vendor_info
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import BitString, ObjectIdentifier, ObjectType
from const import (device_properties_to_read, object_properties_to_read_once,
                   object_properties_to_read_periodically,
                   subscribable_objects)

KeyType = TypeVar("KeyType")


class BACnetIOHandler(NormalApplication):
    bacnet_device_dict: dict = {}
    subscription_tasks: list = []
    update_event: asyncio.Event = asyncio.Event()
    startup_complete: asyncio.Event = asyncio.Event()

    def __init__(self, *args) -> None:
        NormalApplication.__init__(self, *args)
        super().i_am()
        super().who_is()
        self.vendor_info = get_vendor_info(0)
        self.startup_complete.set()
        logging.debug("Initialised application")

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
        logging.debug(f"Updating {updating_mapping}")
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

    async def do_WhoIsRequest(self, apdu) -> None:
        logging.info(f"Received Who Is Request from {apdu.pduSource}")
        await super().do_WhoIsRequest(apdu)

    async def do_IAmRequest(self, apdu) -> None:
        logging.info(f"I Am from {apdu.iAmDeviceIdentifier}")

        if apdu.iAmDeviceIdentifier[1] in self.device_info_cache.instance_cache:
            logging.warning(f"Device {apdu.iAmDeviceIdentifier} already in cache!")
            return

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
            property_value = round(property_value, 2)
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

    async def read_device_props_non_segmented(self, apdu):
        try:
            device_identifier = ObjectIdentifier(apdu.iAmDeviceIdentifier)
            for property_id in device_properties_to_read:
                response = await self.read_property(
                    address=apdu.pduSource, objid=device_identifier, prop=property_id
                )

                if response:
                    self.dict_updater(
                        device_identifier=device_identifier,
                        object_identifier=device_identifier,
                        property_identifier=property_id,
                        property_value=response,
                    )

        except AbortPDU as err:
            logging.error(
                f"Abort PDU error while reading device properties without segmentation: {device_identifier}: {err}"
            )
            if property_id != PropertyIdentifier("objectList"):
                return

            number_of_objects = await self.read_property(
                address=apdu.pduSource,
                objid=device_identifier,
                prop=PropertyIdentifier("objectList"),
                array_index=0
            )

            object_list = []

            for number in range(1, number_of_objects):
                response = await self.read_property(
                    address=apdu.pduSource,
                    objid=device_identifier,
                    prop=PropertyIdentifier("objectList"),
                    array_index=number
                )
                object_list.append(response)

            if object_list:
                self.dict_updater(
                    device_identifier=device_identifier,
                    object_identifier=device_identifier,
                    property_identifier=PropertyIdentifier("objectList"),
                    property_value=object_list,
                )

        except ErrorRejectAbortNack as err:
            logging.error(f"Nack error: {device_identifier}: {err}")
        except AttributeError as err:
            logging.error(f"Attribute error: {err}")

    async def read_device_props(self, apdu) -> bool:
        try:  # Send readPropertyMultiple and get response
            device_identifier = ObjectIdentifier(apdu.iAmDeviceIdentifier)
            parameter_list = [device_identifier] + device_properties_to_read

            logging.debug(f"Exploring Device info of {device_identifier}")

            response = await self.read_property_multiple(
                address=apdu.pduSource, parameter_list=parameter_list
            )

        except AbortPDU as err:
            logging.error(
                f"Abort PDU error while reading device properties: {device_identifier}: {err}"
            )

            if not "segmentation-not-supported" in str(err):
                return False
            else:
                await self.read_device_props_non_segmented(apdu)

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

            parameter_list = [obj_id]
            parameter_list.extend(object_properties_to_read_once)

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

                if not "segmentation-not-supported" in str(err):
                    return False
                else:
                    await self.read_object_list_non_segmented(device_identifier)

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

                parameter_list = [obj_id]
                parameter_list.extend(object_properties_to_read_periodically)

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
            if ObjectIdentifier(object_id)[0] in subscribable_objects:
                await self.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=ObjectIdentifier(object_id),
                    confirmed_notifications=True,
                )

    async def create_subscription_task(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        confirmed_notifications: bool,
        lifetime: int | None = None,
    ):
        device_address = self.dev_to_addr(ObjectIdentifier(device_identifier))
        if confirmed_notifications:
            notifications = "confirmed"
        else:
            notifications = "unconfirmed"

        logging.debug(
            f"Creating {notifications} subscription task {object_identifier} of {device_identifier}"
        )

        task = asyncio.create_task(
            self.subscription_task(
                device_address=device_address,
                object_identifier=ObjectIdentifier(object_identifier),
                confirmed_notification=confirmed_notifications,
                lifetime=lifetime,
            ),
            name=f"{device_identifier[0].attr}:{device_identifier[1]},{object_identifier[0].attr}:{object_identifier[1]},{notifications}",
        )
        self.subscription_tasks.append(task)

    async def end_subscription_tasks(self):
        for task in self.subscription_tasks:
            task.cancel()
        while self.subscription_tasks:
            await asyncio.sleep(1)
        logging.info("Cancelled all subscriptions")

    async def do_ConfirmedCOVNotificationRequest(
        self, apdu: ConfirmedCOVNotificationRequest
    ) -> None:
        await super().do_ConfirmedCOVNotificationRequest(apdu)

    async def do_ReadPropertyRequest(self, apdu: ReadPropertyRequest) -> None:
        try:
            await super().do_ReadPropertyRequest(apdu)
        except (Exception, AttributeError) as err:
            logging.error(
                f"{self.addr_to_dev(apdu.pduSource)} tried to read {apdu.objectIdentifier} {apdu.propertyIdentifier}: {err}"
            )

    async def subscription_task(
        self,
        device_address: Address,
        object_identifier: ObjectIdentifier,
        confirmed_notification: bool,
        lifetime: int | None = None,
    ) -> None:
        try:
            subscription = await self.change_of_value(
                address=device_address,
                monitored_object_identifier=object_identifier,
                subscriber_process_identifier=None,
                issue_confirmed_notifications=confirmed_notification,
                lifetime=lifetime,
            ).__aenter__()
            # create a request to cancel the subscription
            unsubscribe_cov_request = SubscribeCOVRequest(
                subscriberProcessIdentifier=subscription.subscriber_process_identifier,
                monitoredObjectIdentifier=subscription.monitored_object_identifier,
                destination=subscription.address,
            )

            unsubscribe_cov_request.pduDestination = device_address
            subscription.create_refresh_task()
            dev_id = self.addr_to_dev(addr=device_address)
            task_name = f"{dev_id[0].attr}:{dev_id[1]},{object_identifier[0].attr}:{object_identifier[1]}"
            logging.debug(f"Created {task_name} subscription task successfully")
            while True:
                property_identifier, property_value = await subscription.get_value()

                if isinstance(property_value, BitString):
                    property_value = property_value.cast(list())
                elif isinstance(property_value, int | float):
                    property_value = round(property_value, 2)

                self.dict_updater(
                    device_identifier=dev_id,
                    object_identifier=object_identifier,
                    property_identifier=property_identifier,
                    property_value=property_value,
                )

                logging.debug(
                    f"Subscription: {object_identifier}, {property_identifier} = {property_value}"
                )

        except (
            ServicesError,
            AbortException,
            ConfigurationError,
            AttributeError,
        ) as err:
            logging.error(
                f"ServicesError, AbortException or ConfigurationError for: {object_identifier}: {err}"
            )

            await subscription.__aexit__()
            for task in self.subscription_tasks:
                if task_name in task.get_name():
                    index = self.subscription_tasks.index(task)
                    self.subscription_tasks.pop(index)

        except (Exception, InvalidTag, RejectException, ErrorPDU) as err:
            logging.error(
                f"InvalidTag, Reject or ErrorPDU for: {object_identifier}: {err}"
            )

            dev_id = self.addr_to_dev(addr=device_address)
            task_name = f"{dev_id[0].attr}:{dev_id[1]},{object_identifier[0].attr}:{object_identifier[1]}"

            for task in self.subscription_tasks:
                if task_name in task.get_name():
                    index = self.subscription_tasks.index(task)
                    self.subscription_tasks.pop(index)

        except asyncio.CancelledError:
            logging.error(
                f"Cancelled subscription task for: {device_address}, {object_identifier}"
            )

            # send the request, wait for the response
            response = await self.request(unsubscribe_cov_request)

            await subscription.__aexit__()
            for task in self.subscription_tasks:
                if task_name in task.get_name():
                    index = self.subscription_tasks.index(task)
                    self.subscription_tasks.pop(index)
