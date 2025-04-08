"""BACnet handler classes for BACnet add-on."""

import asyncio
import json
from ast import List
from collections.abc import Mapping
from contextvars import Context, ContextVar
from logging import config
from math import e, isinf, isnan
from re import A
from typing import Any, Callable, Dict, TypeVar

import backoff
import bacpypes3
import requests
import websockets
from bacpypes3.apdu import (
    ConfirmedCOVNotificationRequest,
    ErrorRejectAbortNack,
    ReadPropertyMultipleRequest,
    ReadPropertyRequest,
    RejectPDU,
    SimpleAckPDU,
    SubscribeCOVRequest,
    WritePropertyRequest,
)
from bacpypes3.basetypes import (
    EngineeringUnits,
    ErrorType,
    EventState,
    PropertyIdentifier,
    Segmentation,
    ServicesSupported,
)
from bacpypes3.constructeddata import Any as BACpypesAny
from bacpypes3.constructeddata import AnyAtomic, ExtendedList, Sequence
from bacpypes3.errors import *
from bacpypes3.ipv4.app import ForeignApplication, NormalApplication
from bacpypes3.json.util import (
    atomic_encode,
    extendedlist_to_json_list,
    integer_encode,
    octetstring_encode,
    sequence_to_json,
    taglist_to_json_list,
)
from bacpypes3.local.analog import AnalogInputObject, AnalogValueObject
from bacpypes3.local.binary import BinaryInputObject, BinaryValueObject
from bacpypes3.object import CharacterStringValueObject, get_vendor_info
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import (
    Atomic,
    ObjectIdentifier,
    ObjectType,
    OctetString,
    TagList,
)
from bacpypes3.service.cov import SubscriptionContextManager
from const import (
    LOGGER,
    device_properties_to_read,
    object_properties_to_read_once,
    object_properties_to_read_periodically,
    object_types_to_ignore,
    subscribable_objects,
)
from sqlitedict import SqliteDict
from utils import (
    DeviceConfiguration,
    TimeSynchronizationService,
    bitstring_alt_encode,
    enumerated_alt_encode,
    objectidentifier_alt_encode,
)

KeyType = TypeVar("KeyType")
_create_task_delay = 0.001

bacpypes3.json.util.objectidentifier_encode = objectidentifier_alt_encode
bacpypes3.json.util.bitstring_encode = bitstring_alt_encode
bacpypes3.json.util.enumerated_encode = enumerated_alt_encode


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

original_refresh = SubscriptionContextManager.refresh_subscription

async def refresh_subscription_wrapper(self):
    async with self.app.read_semaphore:
        await original_refresh()

SubscriptionContextManager.refresh_subscription = refresh_subscription_wrapper


# reinitializeDevice service


class BACnetIOHandler(
    NormalApplication, ForeignApplication, TimeSynchronizationService
):
    bacnet_device_sqlite: SqliteDict = SqliteDict(
        "/config/bacnet.sqlite", autocommit=True
    )
    bacnet_device_dict: dict = {}
    subscription_tasks: list = []
    update_event: asyncio.Event = asyncio.Event()
    startup_complete: asyncio.Event = asyncio.Event()
    write_to_api: asyncio.Event = asyncio.Event()
    write_to_api_queue: asyncio.Queue = asyncio.Queue()
    subscription_list = []
    i_am_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    poll_tasks: list[asyncio.Task] = []
    addon_device_config: list = []
    init_discovery_complete: asyncio.Event = asyncio.Event()
    read_semaphore: asyncio.Semaphore
    device_configurations: list[DeviceConfiguration] = []

    def __init__(
        self,
        device,
        local_ip,
        foreign_ip="",
        ttl=255,
        update_event=asyncio.Event(),
        addon_device_config=[],
        semaphore: int = 20
    ) -> None:
        if foreign_ip:
            ForeignApplication.__init__(self, device, local_ip)
            self.register(addr=Address(foreign_ip), ttl=int(ttl))
        else:
            NormalApplication.__init__(self, device, local_ip)
        super().i_am()
        self.update_event = update_event
        self.vendor_info = get_vendor_info(0)
        self.addon_device_config = (
            addon_device_config if addon_device_config else list()
        )
        self.sqlite_restore()
        self.read_semaphore = asyncio.Semaphore(semaphore)
        self.startup_complete.set()
        asyncio.get_event_loop().create_task(self.discover_devices())
        asyncio.get_event_loop().create_task(self.sqlite_updater())
        LOGGER.debug("Application initialised")

    def sqlite_restore(self):
        self.deep_update(self.bacnet_device_dict, self.bacnet_device_sqlite)

    async def sqlite_updater(self):
        while True:
            await asyncio.sleep(300)
            self.deep_update(self.bacnet_device_sqlite, self.bacnet_device_dict)

    async def discover_devices(self):
        """Get a list of devices that respond to a whois request"""
        # Get to know the network
        i_ams = await self.who_is(timeout=5)

        generated_configs = []
        retrieved_configs = []

        async def handle_device(i_am):
            """Handle a single device"""
            device_address: Address = i_am.pduSource
            device_identifier: ObjectIdentifier = i_am.iAmDeviceIdentifier

            LOGGER.info(f"Handling I am of {device_identifier}")

            if self.init_discovery_complete.is_set():
                if self.is_in_dict(device_identifier, device_identifier):
                    retrieved_configs.append(self.retrieve_config(device_identifier))
                    return  # Skip if already known

            await self.explore_device(device_identifier)
            configuration = self.generate_config(device_identifier)
            self.device_configurations.append(configuration)
            generated_configs.append(configuration)

        # Run all device handling tasks concurrently
        await asyncio.gather(*(handle_device(i_am) for i_am in i_ams))

        # After running for the first time
        self.init_discovery_complete.set()

        # Generate tasks
        for config in generated_configs + retrieved_configs:
            if config in generated_configs:
                await self.config_to_tasks(config)
            else:
                await self.config_to_tasks(config, False)

    def retrieve_config(
        self, device_identifier: ObjectIdentifier
    ) -> DeviceConfiguration:

        device_id_str = self.identifier_to_string(device_identifier)

        for config in self.device_configurations:
            if self.identifier_to_string(config.device_identifier) == device_id_str:
                return config

        return DeviceConfiguration()

    def generate_config(
        self, device_identifier: ObjectIdentifier
    ) -> DeviceConfiguration:
        configuration = DeviceConfiguration(self.get_config_dict(device_identifier))
        device_id_str = self.identifier_to_string(device_identifier)

        # populate config with actual objects
        object_list = [
            obj
            for obj in self.bacnet_device_dict[device_id_str][device_id_str].get(
                "objectList", []
            )
            if ObjectType(obj[0]) not in object_types_to_ignore
        ]

        if configuration.device_identifier == "all":
            configuration.device_identifier = device_identifier
        elif isinstance(configuration.device_identifier, str):
            try:
                configuration.device_identifier = ObjectIdentifier(
                    configuration.device_identifier
                )
            except Exception as error:
                LOGGER.error(f"We got here... {error}")

        configuration.all_to_objects(object_list)
        # remove object from slow poll if fast polled
        configuration.remove_duplicate_slow_polls()
        # remove object from quick poll if cov
        configuration.remove_duplicate_quick_polls()

        if device_identifier in configuration.cov_items:
            configuration.cov_items.remove(device_identifier)
        if device_identifier in configuration.poll_items_quick:
            configuration.poll_items_quick.remove(device_identifier)
        if device_identifier in configuration.poll_items_slow:
            configuration.poll_items_slow.remove(device_identifier)

        return configuration

    def is_valid_object_class(self, object_identifier: ObjectIdentifier) -> bool:
        object_identifier = ObjectIdentifier(object_identifier)

        object_class = self.vendor_info.get_object_class(object_identifier[0])

        if object_class is None:
            LOGGER.warning(f"Object type is unknown: {object_identifier}")
            return False
        return True

    async def config_to_tasks(
        self, configuration: DeviceConfiguration, first_run: bool = True
    ) -> None:

        device_identifier = ObjectIdentifier(configuration.device_identifier)

        async def create_cov_tasks():

            object_list = [
                item
                for item in configuration.cov_items
                if ObjectType(item[0]) in subscribable_objects
            ]

            for object_identifier in object_list:
                object_identifier = ObjectIdentifier(object_identifier)

                if not self.is_valid_object_class(object_identifier):
                    continue

                if object_identifier[0] in object_types_to_ignore:
                    continue

                if object_identifier == device_identifier:
                    continue

                task_name = f"{self.identifier_to_string(device_identifier)},{self.identifier_to_string(object_identifier)},confirmed"

                if self.task_in_cov_tasklist(task_name):
                    LOGGER.debug(f"task already exists {task_name}")
                    continue

                await self.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    confirmed_notifications=True,
                    lifetime=configuration.cov_lifetime,
                )
                await asyncio.sleep(_create_task_delay)

        async def create_quick_poll_tasks():

            object_list = [item for item in configuration.poll_items_quick]

            for object_identifier in object_list:
                object_identifier = ObjectIdentifier(object_identifier)

                if not self.is_valid_object_class(object_identifier):
                    continue

                if object_identifier[0] in object_types_to_ignore:
                    continue

                if object_identifier == device_identifier:
                    continue

                task_name = f"{self.identifier_to_string(device_identifier)},{self.identifier_to_string(object_identifier)}"

                if self.task_in_poll_tasklist(task_name):
                    LOGGER.debug(f"task already exists {task_name}")
                    continue

                self.create_poll_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    poll_rate=configuration.poll_rate_quick,
                )
                await asyncio.sleep(_create_task_delay)

        async def create_slow_poll_tasks():

            object_list = [item for item in configuration.poll_items_slow]

            for object_identifier in object_list:
                object_identifier = ObjectIdentifier(object_identifier)

                if not self.is_valid_object_class(object_identifier):
                    continue

                if object_identifier[0] in object_types_to_ignore:
                    continue

                if object_identifier == device_identifier:
                    continue

                task_name = f"{self.identifier_to_string(device_identifier)},{self.identifier_to_string(object_identifier)}"

                if self.task_in_poll_tasklist(task_name):
                    LOGGER.debug(f"task already exists {task_name}")
                    continue

                self.create_poll_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    poll_rate=configuration.poll_rate_slow,
                )
                await asyncio.sleep(_create_task_delay)

        if first_run:
            await create_cov_tasks()

            await create_quick_poll_tasks()

            await create_slow_poll_tasks()

            return

        if configuration.reread_on_iam:
            await create_quick_poll_tasks()
            await create_slow_poll_tasks()

        if configuration.resub_on_iam:
            await create_cov_tasks()

    async def explore_device(self, device_identifier: ObjectIdentifier) -> None:
        # Get property list of the device
        property_list = await self.get_property_list(
            device_identifier, device_identifier, device_properties_to_read
        )
        # might have to limit properties read, only intersecting property list with device props to read

        properties_to_read = list(set(property_list) & set(device_properties_to_read))

        # Actually read device properties
        if not await self.properties_read_multiple(
            device_identifier, device_identifier, properties_to_read
        ):
            if not self.is_in_dict(device_identifier, device_identifier):
                LOGGER.warning(
                    f"Failed to get device properties for {device_identifier}"
                )
                return

        # Actually read object properties
        if not await self.read_objects_of_device(device_identifier):
            LOGGER.warning(f"Failed to get object properties for {device_identifier}")

    async def get_property_list(
        self, device_identifier, object_identifier, fallback_list
    ) -> list[PropertyIdentifier]:

        try:
            async with self.read_semaphore:
                property_list = await self.read_property(
                    address=self.dev_to_addr(device_identifier),
                    objid=object_identifier,
                    prop=PropertyIdentifier("propertyList"),
                )
            if isinstance(property_list, list):
                property_list.append(PropertyIdentifier("objectIdentifier"))
                property_list.append(PropertyIdentifier("objectName"))
            else:
                LOGGER.error(f"Invalid property list: {property_list}")
                property_list = fallback_list
        except ErrorRejectAbortNack as err:
            # LOGGER.debug(f"No propertylist for {device_identifier}, {object_identifier}. {err}")
            property_list = fallback_list

        if len(property_list) < 4:
            property_list = fallback_list

        return property_list

    async def properties_read_multiple(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        property_list: list[PropertyIdentifier],
    ) -> bool:
        # Basic useful vars
        device_identifier = ObjectIdentifier(device_identifier)
        object_identifier = ObjectIdentifier(object_identifier)
        parameter_list = [object_identifier, property_list]

        LOGGER.debug(f"Read multiple: {device_identifier} {object_identifier}")
        try:
            async with self.read_semaphore:  # Limit concurrency only for read_property_multiple
                response = await self.read_property_multiple(
                    address=self.dev_to_addr(device_identifier),
                    parameter_list=parameter_list,
                )

        except ErrorRejectAbortNack as err:
            LOGGER.warning(
                f"Error during read multiple: {device_identifier} {object_identifier} {err}"
            )
            if "segmentation-not-supported" in str(
                err
            ) or "unrecognized-service" in str(err):
                return await self.properties_read(
                    device_identifier, object_identifier, property_list
                )
            elif "no-response" in str(err):
                return False
            else:
                return False
        except InvalidTag as err:
            LOGGER.debug(
                f"Invalid tag received: {device_identifier} {object_identifier} {err}"
            )
            return await self.properties_read(
                device_identifier, object_identifier, property_list
            )
        else:
            for (
                object_identifier,
                property_identifier,
                property_array_index,
                property_value,
            ) in response:
                if not isinstance(property_value, ErrorType):
                    self.dict_updater(
                        device_identifier=device_identifier,
                        object_identifier=object_identifier,
                        property_identifier=property_identifier,
                        property_value=property_value,
                    )
            return True

    async def properties_read(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        property_list: list[PropertyIdentifier],
    ) -> bool:
        # Basic useful vars
        device_identifier = ObjectIdentifier(device_identifier)
        object_identifier = ObjectIdentifier(object_identifier)
        LOGGER.debug(f"Read: {device_identifier} {object_identifier}")

        async def read_property_safely(property_id: PropertyIdentifier):
            """Reads a property and handles errors safely."""
            try:
                async with self.read_semaphore:  # Limit concurrency only for read_property
                    response = await self.read_property(
                        address=self.dev_to_addr(device_identifier),
                        objid=object_identifier,
                        prop=property_id,
                    )
            except ErrorRejectAbortNack as err:
                LOGGER.warning(
                    f"Error during read: {device_identifier} {object_identifier} {err}"
                )
                if "segmentation-not-supported" in str(err):
                    return await self.read_list_property(
                        device_identifier, object_identifier, property_id
                    )
                elif "unknown-property" in str(err):
                    return True
                elif "no-response" in str(err):
                    return False
                else:
                    return False
            except InvalidTag as err:
                LOGGER.debug(
                    f"Invalid tag received: {device_identifier} {object_identifier} {err}"
                )
                return False
            else:
                if response is not ErrorType:
                    self.dict_updater(
                        device_identifier=device_identifier,
                        object_identifier=object_identifier,
                        property_identifier=property_id,
                        property_value=response,
                    )
            return True  # Ensure the function returns something in all cases

        # Now outside read_property_safely: create tasks
        tasks = [read_property_safely(property_id) for property_id in property_list]

        # Gather all tasks and wait for completion
        results = await asyncio.gather(*tasks)

        # If any property read returned False (due to "no-response"), return False
        return False if False in results else True

    async def read_list_property(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        property_id: PropertyIdentifier,
    ) -> bool:
        """Read list type property in the smallest possible way."""

        # Basic useful vars
        device_identifier = ObjectIdentifier(device_identifier)
        object_identifier = ObjectIdentifier(object_identifier)
        property_id = PropertyIdentifier(property_id)
        LOGGER.debug(
            f"Read list property: {device_identifier} {object_identifier} {property_id}"
        )
        try:
            async with self.read_semaphore:
                object_amount = await self.read_property(
                    address=self.dev_to_addr(device_identifier),
                    objid=object_identifier,
                    prop=property_id,
                    array_index=0,
                )
            if object_amount == 0:
                LOGGER.debug(
                    f"Amount is zero: {device_identifier} {object_identifier} {property_id}"
                )
                return False
        except ErrorRejectAbortNack as err:
            LOGGER.warning(
                f"Error reading list size for: {device_identifier} {object_identifier} {property_id} {err}"
            )
            return False

        try:
            # Read properties one by one, respecting the semaphore limit
            async def read_with_semaphore(number):
                async with self.read_semaphore:  # Acquire semaphore per task
                    return await self.read_property(
                        address=self.dev_to_addr(device_identifier),
                        objid=object_identifier,
                        prop=property_id,
                        array_index=number,
                    )

            # Create tasks that respect the semaphore limit
            tasks = [
                read_with_semaphore(number) for number in range(1, object_amount + 1)
            ]
            property_list = await asyncio.gather(*tasks)

            self.dict_updater(
                device_identifier=device_identifier,
                object_identifier=object_identifier,
                property_identifier=property_id,
                property_value=property_list,
            )

        except ErrorRejectAbortNack as err:
            LOGGER.warning(
                f"Error reading list size for: {device_identifier} {object_identifier} {property_id} {err}"
            )
            return False
        else:
            return True

    async def read_objects_of_device(self, device_identifier: ObjectIdentifier) -> bool:
        device_identifier = ObjectIdentifier(device_identifier)

        device_id_str = self.identifier_to_string(device_identifier)

        device = self.bacnet_device_dict.get(device_id_str, None)

        if device is None:
            LOGGER.warning(f"Missing device entry for: {device_identifier}")
            return False

        if self.has_read_multiple_service(device_identifier):
            read_func = self.properties_read_multiple
        else:
            read_func = self.properties_read

        tasks = []

        object_list = [
            ObjectIdentifier(obj)
            for obj in device[device_id_str].get("objectList", [])
            if self.is_valid_object_class(ObjectIdentifier(obj))
            and ObjectType(obj[0]) not in object_types_to_ignore
            and ObjectIdentifier(obj) != device_identifier
        ]

        for object_identifier in object_list:
            # Get property list of the device
            property_list = await self.get_property_list(
                device_identifier, object_identifier, object_properties_to_read_once
            )

            properties_to_read = list(
                set(property_list) & set(object_properties_to_read_once)
            )

            tasks.append(
                read_func(device_identifier, object_identifier, properties_to_read)
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        if any(result is False for result in results):
            LOGGER.warning(f"Some properties failed to read for {device_identifier}")

        return True

    def has_read_multiple_service(self, device_identifier: ObjectIdentifier) -> bool:
        device_id_str = self.identifier_to_string(device_identifier)

        services_supported = self.bacnet_device_dict[device_id_str][device_id_str].get(
            "protocolServicesSupported", ServicesSupported()
        )

        if ServicesSupported(services_supported)["read-property-multiple"] != 1:
            return False

        return True

    def has_segmentation(self, device_identifier):
        device_id_str = self.identifier_to_string(device_identifier)

        segmentation = self.bacnet_device_dict[device_id_str][device_id_str].get(
            "segmentationSupported", Segmentation()
        )

        if segmentation in (Segmentation.segmentedBoth, Segmentation.segmentedReceive):
            return True

        return False

    def is_in_dict(
        self, device_identifier: ObjectIdentifier, object_identifier: ObjectIdentifier
    ) -> bool:
        device_id_str = self.identifier_to_string(device_identifier)
        object_id_str = self.identifier_to_string(object_identifier)

        if not self.bacnet_device_dict.get(device_id_str, None):
            return False

        if not self.bacnet_device_dict[device_id_str].get(object_id_str, None):
            return False

        return True

    def get_config_dict(self, device_identifier: ObjectIdentifier) -> dict:
        specific_config = next(
            (
                config
                for config in self.addon_device_config
                if config.get("deviceID")
                == self.identifier_to_string(device_identifier)
            ),
            None,
        )
        if specific_config:
            return specific_config

        generic_config = next(
            (
                config
                for config in self.addon_device_config
                if config.get("deviceID") == f"all"
            ),
            None,
        )
        if generic_config:
            return {
                **generic_config,
                "deviceID": self.identifier_to_string(device_identifier),
            }

        return dict()

    async def object_poll_task(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        poll_rate: int | float = 300,
    ):
        device_identifier = ObjectIdentifier(device_identifier)
        object_identifier = ObjectIdentifier(object_identifier)

        if self.has_read_multiple_service(device_identifier):
            read_func = self.properties_read_multiple
        else:
            read_func = self.properties_read

        property_list = [
            PropertyIdentifier(property_id)
            for property_id in self.bacnet_device_dict[
                self.identifier_to_string(device_identifier)
            ][self.identifier_to_string(object_identifier)]
        ]

        properties_to_read = list(
            set(property_list) & set(object_properties_to_read_periodically)
        )

        while True:
            await asyncio.sleep(poll_rate)

            await read_func(device_identifier, object_identifier, properties_to_read)

    def create_poll_task(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        poll_rate: int = 300,
    ) -> None:
        """Create a task that'll poll every so many seconds."""
        try:
            device_identifier = ObjectIdentifier(device_identifier)
            object_identifier = ObjectIdentifier(object_identifier)

            device_id_str = self.identifier_to_string(device_identifier)
            object_id_str = self.identifier_to_string(object_identifier)

            if not self.is_in_dict(device_identifier, object_identifier):
                LOGGER.warning(
                    f"{device_identifier} not in memory, something went wrong."
                )
                return

            task = asyncio.create_task(
                self.object_poll_task(device_identifier, object_identifier, poll_rate),
                name=f"{device_id_str}{object_id_str}",
            )

            self.poll_tasks.append(task)

        except Exception as err:
            LOGGER.error(
                f"Failed to create polling task {device_identifier}, {object_identifier} {err}"
            )

    def deep_update(
        self, mapping: Dict[KeyType, Any], *updating_mappings: Dict[KeyType, Any]
    ) -> Dict[KeyType, Any]:
        for updating_mapping in updating_mappings:
            for k, v in updating_mapping.items():
                if isinstance(v, Mapping) and isinstance(mapping.get(k), dict):
                    mapping[k] = self.deep_update(mapping[k], v)
                else:
                    mapping[k] = v

        self.update_event.set()
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

    async def do_WhoIsRequest(self, apdu) -> None:
        """Handle incoming Who Is request."""
        LOGGER.info(f"Received Who Is Request from {apdu.pduSource}")
        await super().do_WhoIsRequest(apdu)

    async def do_IAmRequest(self, apdu) -> None:
        """Handle incoming I Am request."""

        LOGGER.info(f"I Am from {apdu.iAmDeviceIdentifier}")

        await super().do_IAmRequest(apdu)

        if not self.init_discovery_complete.is_set():
            return

        config = self.retrieve_config(apdu.iAmDeviceIdentifier)

        await self.config_to_tasks(config, False)

    def identifier_to_string(self, object_identifier: ObjectIdentifier | str) -> str:
        if isinstance(object_identifier, ObjectIdentifier):
            return f"{object_identifier[0].attr}:{object_identifier[1]}"
        else:
            return object_identifier

    def task_in_cov_tasklist(self, task_name) -> bool:
        return any(task_name in task.get_name() for task in self.subscription_tasks)

    def task_in_poll_tasklist(self, task_name) -> bool:
        return any(task_name in task.get_name() for task in self.poll_tasks)

    def dict_updater(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        property_identifier: PropertyIdentifier,
        property_value,
    ):
        if isinstance(property_value, ErrorType):
            LOGGER.info(
                f"Error updating: {device_identifier} {object_identifier} {property_identifier} {sequence_to_json(property_value)}"
            )
            return

        if isinstance(property_value, AnyAtomic):
            property_value = property_value.get_value()
            LOGGER.info(
                f"Get value from AnyAtomic: {device_identifier} {object_identifier} {property_identifier} {property_value}"
            )
        elif isinstance(property_value, BACpypesAny):
            object_class = self.vendor_info.get_object_class(object_identifier[0])
            property_type = object_class.get_property_type(property_identifier)

            property_value = property_value.cast_out(property_type)

            LOGGER.info(
                f"Cast Any as {property_type} for: {device_identifier} {object_identifier} {property_identifier} {property_value}"
            )

        if isinstance(property_value, Atomic):
            property_value = atomic_encode(property_value)

        elif isinstance(property_value, Sequence):
            property_value = sequence_to_json(property_value)

        elif isinstance(property_value, ExtendedList):
            property_value = extendedlist_to_json_list(property_value)

        elif isinstance(property_value, TagList):
            property_value = taglist_to_json_list(property_value)

        elif isinstance(property_value, (list, tuple)):
            property_value = extendedlist_to_json_list(property_value)

        else:
            LOGGER.warning(
                f"Unknown type {type(property_value)}: {device_identifier} {object_identifier} {property_identifier} {property_value}"
            )
            return

        if isinstance(property_value, float):
            if isnan(property_value):
                LOGGER.info(
                    f"NaN property cast as None: {device_identifier}, {object_identifier}, {property_identifier}... NaN value: {property_value}"
                )
                property_value = None
            elif isinf(property_value):
                LOGGER.info(
                    f"Inf property cast as None: {device_identifier}, {object_identifier}, {property_identifier}... Inf value: {property_value}"
                )
                property_value = None
            else:
                property_value = round(property_value, 4)

        self.deep_update(
            self.bacnet_device_dict,
            {
                self.identifier_to_string(device_identifier): {
                    self.identifier_to_string(object_identifier): {
                        property_identifier.attr: property_value
                    }
                }
            },
        )

    async def create_subscription_task(
        self,
        device_identifier: ObjectIdentifier,
        object_identifier: ObjectIdentifier,
        confirmed_notifications: bool,
        lifetime: int | None = None,
        done_callback: Callable | None = lambda x: None,
    ):
        device_address = self.dev_to_addr(ObjectIdentifier(device_identifier))
        if confirmed_notifications:
            notifications = "confirmed"
        else:
            notifications = "unconfirmed"

        object_identifier = ObjectIdentifier(object_identifier)

        task = asyncio.create_task(
            self.subscription_task(
                device_address=device_address,
                object_identifier=ObjectIdentifier(object_identifier),
                confirmed_notification=confirmed_notifications,
                lifetime=lifetime,
            ),
            name=f"{device_identifier[0].attr}:{device_identifier[1]},{object_identifier[0].attr}:{object_identifier[1]},{notifications}",
        )

        await asyncio.sleep(_create_task_delay)

        task.add_done_callback(done_callback)

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

        device_context = ContextVar("device_context")
        device_context.set(device_identifier)

        object_context = ContextVar("object_context")
        object_context.set(object_identifier)

        confirmation_context = ContextVar("confirmation_context")
        confirmation_context.set(notifications)

        lifetime_context = ContextVar("lifetime_context")
        lifetime_context.set(lifetime)
        lifetime_remaining_context = ContextVar("lifetime_remaining_context")

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

                object_class = self.vendor_info.get_object_class(
                    subscription.monitored_object_identifier[0]
                )

                LOGGER.debug(f"Created {task_name} subscription task successfully")

                while True:
                    try:
                        property_identifier, property_value = await asyncio.wait_for(
                            subscription.get_value(), 60
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

                        if not subscription.refresh_subscription_task:
                            continue

                        if subscription.refresh_subscription_task.done():
                            # check for exceptions (gets raised by result if there is)
                            subscription.refresh_subscription_task.result()

                        continue

                    except Exception:
                        raise

                    lifetime_remaining_context.set(
                        subscription.refresh_subscription_handle.when()
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
            object_identifier = apdu.objectIdentifier

            obj = self.get_object_id(object_identifier)

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
                    (
                        object_identifier,
                        property_type,
                        array_index,
                        priority,
                        property_value,
                    )
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
