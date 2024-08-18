"""BACnet handler classes for BACnet add-on."""

import asyncio
import json
from ast import List
from logging import config
from math import e, isinf, isnan
from re import A
from typing import Any, Dict, TypeVar

import backoff
import requests
import websockets
from bacpypes3.apdu import (AbortPDU, ConfirmedCOVNotificationRequest,
                            ErrorPDU, ErrorRejectAbortNack,
                            ReadPropertyMultipleRequest, ReadPropertyRequest,
                            RejectPDU, SimpleAckPDU, SubscribeCOVRequest,
                            UnconfirmedCOVNotificationRequest,
                            WritePropertyRequest)
from bacpypes3.basetypes import (BinaryPV, DeviceStatus, EngineeringUnits,
                                 ErrorClass, ErrorCode, ErrorType, EventState,
                                 PropertyIdentifier, ReadAccessResult,
                                 Reliability, ServicesSupported)
from bacpypes3.constructeddata import AnyAtomic
from bacpypes3.debugging import bacpypes_debugging
from bacpypes3.errors import *
from bacpypes3.ipv4.app import ForeignApplication, NormalApplication
from bacpypes3.json.util import octetstring_encode
from bacpypes3.local.analog import AnalogInputObject, AnalogValueObject
from bacpypes3.local.binary import BinaryInputObject, BinaryValueObject
from bacpypes3.object import CharacterStringValueObject, get_vendor_info
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier, ObjectType, OctetString
from bacpypes3.service.cov import SubscriptionContextManager
from const import (LOGGER, device_properties_to_read,
                   object_properties_to_read_once,
                   object_properties_to_read_periodically,
                   subscribable_objects)

KeyType = TypeVar("KeyType")
_debug = 0


def custom_init(
    self,
    app: "Application",  # noqa: F821
    address: Address,
    monitored_object_identifier: ObjectIdentifier,
    subscriber_process_identifier: int,
    issue_confirmed_notifications: bool,
    lifetime: int,
):
    original_init(
        self,
        app,
        address,
        monitored_object_identifier,
        subscriber_process_identifier,
        issue_confirmed_notifications,
        lifetime,
    )

    # result of refresh task to check if exception occurred
    self.refresh_subscription_task = None


original_init = SubscriptionContextManager.__init__

SubscriptionContextManager.__init__ = custom_init


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
    default_subscription_lifetime = 60
    subscription_list = []
    i_am_queue: asyncio.Queue = asyncio.Queue()
    poll_tasks: list[asyncio.Task] = []
    addon_device_config: list = []

    def __init__(
        self,
        device,
        local_ip,
        foreign_ip="",
        ttl=255,
        update_event=asyncio.Event(),
        addon_device_config=[],
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
        asyncio.get_event_loop().create_task(self.IAm_handler())
        self.addon_device_config = addon_device_config
        self.startup_complete.set()
        LOGGER.debug("Application initialised")

    async def generate_specific_tasks(
        self, device_identifier: ObjectIdentifier
    ) -> None:
        """Handle generating tasks for specific identifiers after reading object."""

        specific_config = [
            config
            for config in self.addon_device_config
            if config.get("deviceID")
            == f"{device_identifier[0]}:{device_identifier[1]}"
        ]

        if not specific_config:
            # assume generic handling
            await self.generate_generic_tasks(device_identifier=device_identifier)
            return

        if len(specific_config) > 1:
            # duplicate
            return

        index = self.addon_device_config.index(specific_config[0])

        config = self.addon_device_config[index]

        if config.get("quick_poll_list", []):
            await self.create_poll_task(
                device_identifier=device_identifier,
                object_list=config.get("quick_poll_list"),
                poll_rate=config.get("quick_poll_rate", 30),
            )

        if "all" in config.get("slow_poll_list", []):
            object_list = self.bacnet_device_dict[f"device:{device_identifier[1]}"][
                f"device:{device_identifier[1]}"
            ].get("objectList")

            if device_identifier in object_list:
                object_list.remove(device_identifier)

        elif config.get("slow_poll_list", []):
            object_list = config.get("slow_poll_list", [])
        else:
            object_list = []

        if object_list:
            await self.create_poll_task(
                device_identifier=device_identifier,
                object_list=object_list,
                poll_rate=config.get("slow_poll_rate", 600),
            )

        if "all" in config.get("CoV_list", []):
            object_list = self.bacnet_device_dict[f"device:{device_identifier[1]}"][
                f"device:{device_identifier[1]}"
            ].get("objectList")

            if device_identifier in object_list:
                object_list.remove(device_identifier)

            object_list = [
                object_identifier
                for object_identifier in object_list
                if object_identifier[0] in subscribable_objects
            ]

            for object_identifier in object_list:
                await self.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    confirmed_notifications=True,
                    lifetime=config.get(
                        "CoV_lifetime", self.default_subscription_lifetime
                    ),
                )
                await asyncio.sleep(0)

        elif config.get("CoV_list", []):
            for object_identifier in config.get("CoV_list"):
                await self.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    confirmed_notifications=True,
                    lifetime=config.get("CoV_lifetime"),
                )
                await asyncio.sleep(0)

        return

    async def generate_generic_tasks(self, device_identifier: ObjectIdentifier) -> None:
        specific_config = [
            config
            for config in self.addon_device_config
            if config.get("deviceID") == "all"
        ]

        if not specific_config:
            # use generic settings:
            await self.subscribe_object_list(device_identifier=device_identifier)
            return

        index = self.addon_device_config.index(specific_config[0])

        config = self.addon_device_config[index]

        if config.get("quick_poll_list", []):
            await self.create_poll_task(
                device_identifier=device_identifier,
                object_list=config.get("quick_poll_list"),
                poll_rate=config.get("quick_poll_rate", 30),
            )

        if "all" in config.get("slow_poll_list", []):
            object_list = self.bacnet_device_dict[f"device:{device_identifier[1]}"][
                f"device:{device_identifier[1]}"
            ].get("objectList")

            if device_identifier in object_list:
                object_list.remove(device_identifier)

        elif config.get("slow_poll_list", []):
            object_list = config.get("slow_poll_list")
        else:
            object_list = []

        if object_list:
            await self.create_poll_task(
                device_identifier=device_identifier,
                object_list=object_list,
                poll_rate=config.get(
                    "slow_poll_rate", self.default_subscription_lifetime
                ),
            )

        if "all" in config.get("CoV_list", []):
            object_list = self.bacnet_device_dict[f"device:{device_identifier[1]}"][
                f"device:{device_identifier[1]}"
            ].get("objectList")
            if device_identifier in object_list:
                object_list.remove(device_identifier)

            object_list = [
                object_identifier
                for object_identifier in object_list
                if object_identifier[0] in subscribable_objects
            ]

            for object_identifier in object_list:
                await self.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    confirmed_notifications=True,
                    lifetime=config.get("CoV_lifetime", 600),
                )
                await asyncio.sleep(0)

        elif config.get("CoV_list", []):
            for object_identifier in config.get("CoV_list"):
                await self.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    confirmed_notifications=True,
                    lifetime=config.get("CoV_lifetime", 600),
                )
                await asyncio.sleep(0)

        return

    async def poll_task(
        self,
        device_identifier: ObjectIdentifier,
        object_list: list[ObjectIdentifier],
        poll_rate: int = 30,
    ) -> None:
        LOGGER.debug(f"TASK: {device_identifier} {object_list} {device_identifier}")

        try:
            services_supported = self.bacnet_device_dict[
                f"device:{device_identifier[1]}"
            ][f"device:{device_identifier[1]}"].get(
                "protocolServicesSupported", ServicesSupported()
            )

            while True:
                for object_identifier in object_list:
                    object_class = self.vendor_info.get_object_class(
                        object_identifier[0]
                    )

                    if object_class is None:
                        LOGGER.warning(
                            f"Object type is unknown: {device_identifier}, {object_identifier}"
                        )
                        continue

                    if services_supported["read-property-multiple"] == 1:
                        try:
                            response = await self.read_property_multiple(
                                address=self.dev_to_addr(device_identifier),
                                parameter_list=[
                                    object_identifier,
                                    object_properties_to_read_periodically,
                                ],
                            )
                        except ErrorRejectAbortNack as err:
                            LOGGER.error(
                                f"Read multiple error: {device_identifier} {object_identifier}: {err}"
                            )
                            continue
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
                    else:
                        for property_id in object_properties_to_read_periodically:
                            property_class = object_class.get_property_type(property_id)

                            if property_class is None:
                                continue

                            try:
                                response = await self.read_property(
                                    address=self.dev_to_addr(device_identifier),
                                    objid=object_identifier,
                                    prop=property_id,
                                )
                            except ErrorRejectAbortNack as err:
                                LOGGER.error(
                                    f"Read error: {device_identifier} {object_identifier} {property_id}: {err}"
                                )
                                continue
                            else:
                                if response is not ErrorType:
                                    self.dict_updater(
                                        device_identifier=device_identifier,
                                        object_identifier=object_identifier,
                                        property_identifier=property_id,
                                        property_value=response,
                                    )

                await asyncio.sleep(poll_rate)

        except asyncio.CancelledError as err:
            LOGGER.info(f"Poll task for {device_identifier} cancelled")

        except Exception as err:
            LOGGER.error(err)

    async def create_poll_task(
        self,
        device_identifier: ObjectIdentifier,
        object_list: list[ObjectIdentifier],
        poll_rate: int = 30,
    ) -> None:
        """Create a task that'll poll every so many seconds."""
        try:
            LOGGER.debug(
                f"Creating poll task: {device_identifier} {object_list} {poll_rate}"
            )

            device_identifier = ObjectIdentifier(device_identifier)

            if not self.bacnet_device_dict.get(f"device:{device_identifier[1]}"):
                await asyncio.sleep(15)

            if not self.bacnet_device_dict.get(f"device:{device_identifier[1]}"):
                self.who_is(device_identifier[1], device_identifier[1])
                await asyncio.sleep(45)

            if not self.bacnet_device_dict.get(f"device:{device_identifier[1]}"):
                LOGGER.warning(
                    f"{device_identifier} did not respond the requests. No polling possible."
                )
                return

            objects_to_poll: list = []

            for object_identifier in object_list:
                object_identifier = ObjectIdentifier(object_identifier)

                if not self.bacnet_device_dict[f"device:{device_identifier[1]}"].get(
                    f"{object_identifier[0]}:{object_identifier[1]}"
                ):
                    try:
                        response = await self.read_property(
                            address=self.dev_to_addr(device_identifier),
                            objid=object_identifier,
                            prop=PropertyIdentifier("presentValue"),
                        )
                    except ErrorRejectAbortNack as err:
                        LOGGER.warning(
                            f"{device_identifier} {object_identifier} failed to read: {err}"
                        )
                        LOGGER.info(
                            f"{device_identifier} {object_identifier} won't get polled."
                        )
                        continue

                objects_to_poll.append(object_identifier)

            if not objects_to_poll:
                LOGGER.warning(f"No objects to poll for {device_identifier}.")
                return

            task = asyncio.create_task(
                self.poll_task(device_identifier, objects_to_poll, poll_rate),
                name=f"{device_identifier[0]}:{device_identifier[1]}",
            )

            self.poll_tasks.append(task)

        except Exception as err:
            LOGGER.error(
                f"Failed to create polling task {device_identifier}, {object_identifier}"
            )

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

        for address, device_info in self.device_info_cache.address_cache.items():
            if device_info.device_instance == dev[1]:
                return address

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
            await self.device_info_cache.set_device_info(apdu)
            in_cache = True
        else:
            await self.device_info_cache.set_device_info(apdu)
            in_cache = False

        await super().do_IAmRequest(apdu)

        if not in_cache:
            await self.i_am_queue.put(apdu)
        else:
            # Check if object list is still the same, otherwise read entire dict again
            await self.handle_object_list_check(apdu)

            # Check if CoV tasks are still active, otherwise resub.
            await self.handle_cov_check(apdu.iAmDeviceIdentifier)

    async def handle_object_list_check(self, apdu) -> None:

        device_id = apdu.iAmDeviceIdentifier[1]

        object_list = self.bacnet_device_dict[f"device:{apdu.iAmDeviceIdentifier[1]}"][
            f"device:{apdu.iAmDeviceIdentifier[1]}"
        ].get("objectList")

        if not await self.read_multiple_device_props(apdu=apdu):
            LOGGER.warning(f"Failed to get: {device_id}, {device_id}")
            if self.bacnet_device_dict.get(f"device:{device_id}"):
                self.bacnet_device_dict.pop(f"device:{device_id}")

        if object_list != self.bacnet_device_dict[
            f"device:{apdu.iAmDeviceIdentifier[1]}"
        ][f"device:{apdu.iAmDeviceIdentifier[1]}"].get("objectList"):
            LOGGER.warning(f"Not implemented yet: object lists aren't equal!")

    def identifier_to_string(self, object_identifier) -> str:
        return f"{object_identifier[0].attr}:{object_identifier[1]}"

    def task_in_tasklist(self, task_name) -> bool:
        return any(task_name in task.get_name() for task in self.subscription_tasks)

    async def handle_cov_check(self, device_identifier) -> None:

        device_string = self.identifier_to_string(device_identifier)

        if self.addon_device_config is None:
            return

        specific_config = [
            config
            for config in self.addon_device_config
            if config.get("deviceID")
            == f"{device_identifier[0]}:{device_identifier[1]}"
        ]

        if not specific_config:
            specific_config = [
                config
                for config in self.addon_device_config
                if config.get("deviceID") == "all"
            ]
            if not specific_config:
                return

        index = self.addon_device_config.index(specific_config[0])

        config = self.addon_device_config[index]

        if "all" in config.get("CoV_list", []):
            object_list = self.bacnet_device_dict[f"device:{device_identifier[1]}"][
                f"device:{device_identifier[1]}"
            ].get("objectList")

            if device_identifier in object_list:
                object_list.remove(device_identifier)

            object_list = [
                object_identifier
                for object_identifier in object_list
                if object_identifier[0] in subscribable_objects
            ]

            for object_identifier in object_list:

                task_name = f"{self.identifier_to_string(device_identifier)},{self.identifier_to_string(object_identifier)},confirmed"

                if self.task_in_tasklist(task_name):
                    continue

                await self.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    confirmed_notifications=True,
                    lifetime=config.get(
                        "CoV_lifetime", self.default_subscription_lifetime
                    ),
                )
                await asyncio.sleep(0)

        elif config.get("CoV_list", []):

            for object_identifier in config.get("CoV_list"):

                task_name = f"{self.identifier_to_string(device_identifier)},{self.identifier_to_string(object_identifier)},confirmed"

                if self.task_in_tasklist(task_name):
                    continue

                await self.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    confirmed_notifications=True,
                    lifetime=config.get("CoV_lifetime"),
                )
                await asyncio.sleep(0)

    async def IAm_handler(self):
        """Do the things when receiving I Am requests"""

        while True:
            try:
                apdu = await self.i_am_queue.get()

                device_id = apdu.iAmDeviceIdentifier[1]

                # if failed stop handling response
                if not await self.read_multiple_device_props(apdu=apdu):
                    LOGGER.warning(f"Failed to get: {device_id}, {device_id}")
                    if self.bacnet_device_dict.get(f"device:{device_id}"):
                        self.bacnet_device_dict.pop(f"device:{device_id}")
                    continue

                if not self.bacnet_device_dict.get(f"device:{device_id}"):
                    LOGGER.warning(f"Failed to get: {device_id}")
                    continue

                if not self.bacnet_device_dict[f"device:{device_id}"].get(
                    f"device:{device_id}"
                ):
                    LOGGER.warning(f"Failed to get: {device_id}, {device_id}")
                    continue

                services_supported = self.bacnet_device_dict[f"device:{device_id}"][
                    f"device:{device_id}"
                ].get("protocolServicesSupported", ServicesSupported())

                if services_supported["read-property-multiple"] == 1:
                    await self.read_multiple_objects(
                        device_identifier=apdu.iAmDeviceIdentifier
                    )
                else:
                    await self.read_objects(device_identifier=apdu.iAmDeviceIdentifier)

                if self.addon_device_config:
                    await self.generate_specific_tasks(
                        device_identifier=apdu.iAmDeviceIdentifier
                    )
                else:
                    await self.subscribe_object_list(
                        device_identifier=apdu.iAmDeviceIdentifier
                    )

            except Exception as err:
                LOGGER.error(f"I Am Handler failed {apdu.iAmDeviceIdentifier}: {err}")

    def dict_updater(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        property_identifier: PropertyIdentifier,
        property_value,
    ):
        if isinstance(property_value, ErrorType):
            return
        elif property_value is None or property_identifier is None:
            LOGGER.debug(
                f"NoneType property (identifier) value: {device_identifier}, {object_identifier}, {property_identifier} {property_value}"
            )
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
            LOGGER.debug(
                f"AnyAtomic property value: {device_identifier}, {object_identifier}, {property_identifier} {property_value}"
            )
            property_value = property_value.get_value()

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

        if isinstance(property_value, list) and all(
            isinstance(item, ReadAccessResult) for item in property_value
        ):
            LOGGER.debug(
                f"ReadAccessResult property value: {device_identifier}, {object_identifier}, {property_identifier} {property_value}"
            )
            return  # ignore for now...

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
            (EventState, DeviceStatus, EngineeringUnits, Reliability, BinaryPV),
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
        elif isinstance(property_value, OctetString):
            self.deep_update(
                self.bacnet_device_dict,
                {
                    f"{device_identifier[0]}:{device_identifier[1]}": {
                        f"{object_identifier[0].attr}:{object_identifier[1]}": {
                            property_identifier.attr: octetstring_encode(property_value)
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

            LOGGER.debug(f"Reading device properties of {device_identifier}")

            response = await self.read_property_multiple(
                address=apdu.pduSource, parameter_list=parameter_list
            )

        except ErrorRejectAbortNack as err:
            LOGGER.error(f"Error reading device props: {device_identifier}: {err}")

            if "segmentation-not-supported" in str(err):
                return await self.read_device_props(apdu)
            elif "unrecognized-service" in str(err):
                return await self.read_device_props(apdu)
            elif "no-response" in str(err):
                return False
            else:
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
                if property_value is not ErrorType:
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

        LOGGER.debug(f"Reading device properties of {device_identifier} one by one.")

        for property_id in device_properties_to_read:
            if property_id == PropertyIdentifier("objectList"):
                continue

            try:
                response = await self.read_property(
                    address=address, objid=device_identifier, prop=property_id
                )
            except ErrorRejectAbortNack as err:
                LOGGER.error(
                    f"Error reading device properties one by one: {device_identifier}: {property_id} {err}"
                )

                if "no-response" in str(err):
                    return False

                continue
            except AttributeError as err:
                LOGGER.error(
                    f"Attribute error reading device properties one by one: {device_identifier}: {property_id} {err}"
                )
                continue
            except ValueError as err:
                LOGGER.error(
                    f"ValueError reading device props one by one: {device_identifier}: {property_id} {err}"
                )
                continue
            except Exception as err:
                LOGGER.error(
                    f"Exception reading device props one by one: {device_identifier}: {property_id} {err}"
                )
                continue
            else:
                if response is not ErrorType:
                    self.dict_updater(
                        device_identifier=device_identifier,
                        object_identifier=device_identifier,
                        property_identifier=property_id,
                        property_value=response,
                    )

        if await self.read_object_list_property(device_identifier):
            return True
        else:
            return False

    async def read_object_list_property(self, device_identifier) -> bool:
        """Read object list property in the smallest possible way."""
        address = self.dev_to_addr(dev=device_identifier)

        LOGGER.debug(f"Reading objectList property of {device_identifier} one by one.")

        try:
            object_amount = await self.read_property(
                address=address,
                objid=device_identifier,
                prop=PropertyIdentifier("objectList"),
                array_index=0,
            )

            if object_amount == 0:
                return False
        except ErrorRejectAbortNack as err:
            LOGGER.warning(
                f"Error getting object list size for {device_identifier} at {address}: {err}"
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
        except ErrorRejectAbortNack as err:
            LOGGER.warning(
                f"Error getting object list size for {device_identifier} at {address}: {err}"
            )
            return False
        else:
            return True

    async def read_multiple_objects(self, device_identifier):
        """Read all objects from a device."""
        LOGGER.info(f"Reading objects from objectList of {device_identifier}...")
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
                response = await self.read_property_multiple(
                    address=self.dev_to_addr(device_identifier),
                    parameter_list=parameter_list,
                )

            except ErrorRejectAbortNack as err:
                LOGGER.error(
                    f"Error while reading object list: {device_identifier}: {obj_id} {err}"
                )

                if "unrecognized-service" in str(err):
                    await self.read_objects(device_identifier)
                    return
                elif "segmentation-not-supported" in str(err):
                    await self.read_objects(device_identifier)
                    return
                elif "no-response" in str(err):
                    return False

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

    async def read_objects(self, device_identifier):
        try:
            for obj_id in self.bacnet_device_dict[f"device:{device_identifier[1]}"][
                f"device:{device_identifier[1]}"
            ].get("objectList", []):
                if not isinstance(obj_id, ObjectIdentifier):
                    obj_id = ObjectIdentifier(obj_id)

                if (
                    ObjectType(obj_id[0]) == ObjectType("device")
                    or ObjectType(obj_id[0])
                    not in self.vendor_info.registered_object_classes
                ):
                    continue

                object_class = self.vendor_info.get_object_class(obj_id[0])

                if object_class is None:
                    LOGGER.warning(
                        f"Object type is unknown: {device_identifier}, {obj_id}"
                    )
                    continue

                for property_id in object_properties_to_read_once:
                    property_class = object_class.get_property_type(property_id)

                    if property_class is None:
                        continue

                    try:
                        response = await self.read_property(
                            address=self.dev_to_addr(device_identifier),
                            objid=obj_id,
                            prop=property_id,
                        )
                    except ErrorRejectAbortNack as err:
                        LOGGER.error(
                            f"Error reading object list one by one: {device_identifier} {obj_id} {property_id}: {err}"
                        )
                        if "no-response" in str(err):
                            return False
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
                response = await self.read_property_multiple(
                    address=self.dev_to_addr(ObjectIdentifier(device_identifier)),
                    parameter_list=parameter_list,
                )

            except ErrorRejectAbortNack as err:
                LOGGER.error(
                    f"Error reading objects periodically:{device_identifier}, {obj_id}: {err}"
                )
                if "unrecognized-service" in str(err):
                    await self.read_objects_periodically(device_identifier)
                    return
                elif "segmentation-not-supported" in str(err):
                    await self.read_objects_periodically(device_identifier)
                    return
                elif "no-response" in str(err):
                    return False

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
        LOGGER.info(f"Reading objects for {device_identifier}...")
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

            object_class = self.vendor_info.get_object_class(obj_id[0])

            if object_class is None:
                LOGGER.warning(f"Object type is unknown: {device_identifier}, {obj_id}")
                continue

            for property_id in object_properties_to_read_periodically:
                property_class = object_class.get_property_type(property_id)

                if property_class is None:
                    continue

                try:
                    response = await self.read_property(
                        address=self.dev_to_addr(device_identifier),
                        objid=obj_id,
                        prop=property_id,
                    )

                except ErrorRejectAbortNack as err:
                    LOGGER.error(
                        f"Error reading objects one by one periodically: {device_identifier} {obj_id} {property_id}: {err}"
                    )
                    if "no-response" in str(err):
                        return False
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
                await asyncio.sleep(0)

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

        object_identifier = ObjectIdentifier(object_identifier)

        LOGGER.debug(
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
        await asyncio.sleep(0.1)
        self.subscription_tasks.append(task)

    async def subscription_task(
        self,
        device_address: Address,
        object_identifier: ObjectIdentifier,
        confirmed_notification: bool,
        lifetime: int | None = None,
    ) -> None:
        """Task with context manager to handle CoV."""

        device_identifier = self.addr_to_dev(addr=device_address)

        if confirmed_notification:
            notifications = "confirmed"
        else:
            notifications = "unconfirmed"

        task_name = f"{device_identifier[0].attr}:{device_identifier[1]},{object_identifier[0].attr}:{object_identifier[1]},{notifications}"

        unsubscribe_cov_request = None

        try:
            async with self.change_of_value(
                address=device_address,
                monitored_object_identifier=object_identifier,
                subscriber_process_identifier=None,
                issue_confirmed_notifications=confirmed_notification,
                lifetime=lifetime,
            ) as subscription:
                # create a request to cancel the subscription
                unsubscribe_cov_request = SubscribeCOVRequest(
                    subscriberProcessIdentifier=subscription.subscriber_process_identifier,
                    monitoredObjectIdentifier=subscription.monitored_object_identifier,
                    destination=subscription.address,
                )

                unsubscribe_cov_request.pduDestination = device_address

                LOGGER.debug(f"Created {task_name} subscription task successfully")

                while True:
                    try:
                        property_identifier, property_value = await asyncio.wait_for(
                            subscription.get_value(), 10
                        )
                    except asyncio.TimeoutError:
                        # check if address has changes
                        if subscription.address != self.dev_to_addr(
                            dev=device_identifier
                        ):
                            old_key = (
                                subscription.address,
                                subscription.subscriber_process_identifier,
                            )
                            self._cov_contexts.pop(old_key)

                            subscription.address = self.dev_to_addr(
                                dev=device_identifier
                            )

                            new_key = (
                                subscription.address,
                                subscription.subscriber_process_identifier,
                            )

                            self._cov_contexts[new_key] = subscription

                        if not isinstance(
                            subscription.refresh_subscription_task, asyncio.Task
                        ):
                            continue

                        if subscription.refresh_subscription_task.done():
                            # check for exceptions (gets raised by result if there is)
                            subscription.refresh_subscription_task.result()

                        continue

                    except Exception:
                        raise

                    object_class = self.vendor_info.get_object_class(
                        subscription.monitored_object_identifier[0]
                    )
                    property_type = object_class.get_property_type(property_identifier)

                    if property_type is None or property_value is None:
                        LOGGER.warning(
                            f"NoneType property: {subscription.monitored_object_identifier} {property_identifier} {property_value}"
                        )
                        continue
                    elif property_identifier not in object_properties_to_read_once:
                        LOGGER.warning(
                            f"Ignoring property: {subscription.monitored_object_identifier[0]} {property_identifier} {property_value}"
                        )
                        continue

                    LOGGER.debug(
                        f"{notifications} CoV: {device_identifier} {object_identifier} {property_identifier} {property_value}"
                    )

                    self.dict_updater(
                        device_identifier=device_identifier,
                        object_identifier=object_identifier,
                        property_identifier=property_identifier,
                        property_value=property_value,
                    )

        except ErrorRejectAbortNack as err:
            LOGGER.error(
                f"ErrorRejectAbortNack: {self.addr_to_dev(device_address)}, {object_identifier}: {err}"
            )

            for task in self.subscription_tasks:
                if task_name in task.get_name():
                    index = self.subscription_tasks.index(task)
                    self.subscription_tasks.pop(index)

        except AbortPDU as err:
            LOGGER.error(f"{err}")

        except asyncio.CancelledError as err:
            LOGGER.error(
                f"Cancelling subscription task: {device_identifier}, {object_identifier}: {err}"
            )

            # send the request, wait for the response
            if unsubscribe_cov_request:
                response = await self.request(unsubscribe_cov_request)

            for task in self.subscription_tasks:
                if task_name in task.get_name():
                    index = self.subscription_tasks.index(task)
                    self.subscription_tasks.pop(index)

        except Exception as err:
            LOGGER.error(f"Error: {device_identifier}, {object_identifier}: {err}")

            # send the request, wait for the response
            if unsubscribe_cov_request:
                response = await self.request(unsubscribe_cov_request)

            for task in self.subscription_tasks:
                if task_name in task.get_name():
                    index = self.subscription_tasks.index(task)
                    self.subscription_tasks.pop(index)

    async def end_subscription_tasks(self):
        for task in self.subscription_tasks:
            task.cancel()
        while self.subscription_tasks:
            await asyncio.sleep(2)
        LOGGER.info("Cancelled all subscriptions")

    async def do_ConfirmedCOVNotificationRequest(
        self, apdu: ConfirmedCOVNotificationRequest
    ) -> None:

        address = apdu.pduSource
        subscriber_process_identifier = apdu.subscriberProcessIdentifier

        # find the context
        scm = self._cov_contexts.get((address, subscriber_process_identifier), None)

        if not scm:
            await asyncio.sleep(0.1)
            scm = self._cov_contexts.get((address, subscriber_process_identifier), None)

        if (not scm) or (
            apdu.monitoredObjectIdentifier != scm.monitored_object_identifier
        ):
            raise ServicesError(errorCode="unknownSubscription")

        # queue the property values
        for property_value in apdu.listOfValues:
            await scm.put(property_value)

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

    async def do_ReadPropertyMultipleRequest(
        self, apdu: ReadPropertyMultipleRequest
    ) -> None:
        try:
            await super().do_ReadPropertyMultipleRequest(apdu)
        except (Exception, AttributeError) as err:
            for read_access_spec in apdu.listOfReadAccessSpecs:
                property_list = [
                    property_id.propertyIdentifier
                    for property_id in read_access_spec.listOfPropertyReferences
                ]

                LOGGER.warning(
                    f"{self.addr_to_dev(apdu.pduSource)} failed to read {read_access_spec.objectIdentifier} {property_list}: {err}"
                )
            await super().do_ReadPropertyMultipleRequest(apdu)

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
                else EngineeringUnits("noUnits")
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
            return EngineeringUnits("noUnits")

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
        elif unit == "V":
            bacnetUnits = EngineeringUnits("volts")
        elif unit == "mV":
            bacnetUnits = EngineeringUnits("millivolts")
        elif unit == "hPa":
            bacnetUnits = EngineeringUnits("hectopascals")
        elif unit == "\u00b5\u0067\u002f\u006d\u00b3":
            bacnetUnits = EngineeringUnits("microgramsPerCubicMeter")
        elif unit == "\u006d\u00b3":
            bacnetUnits = EngineeringUnits("cubicMeters")
        elif unit == "s":
            bacnetUnits = EngineeringUnits("seconds")
        elif unit == "min":
            bacnetUnits = EngineeringUnits("minutes")
        elif unit == "h":
            bacnetUnits = EngineeringUnits("hours")
        elif unit == "d":
            bacnetUnits = EngineeringUnits("days")
        elif unit == "w":
            bacnetUnits = EngineeringUnits("weeks")
        elif unit == "m":
            bacnetUnits = EngineeringUnits("months")
        elif unit == "y":
            bacnetUnits = EngineeringUnits("years")
        else:
            bacnetUnits = EngineeringUnits("noUnits")
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
