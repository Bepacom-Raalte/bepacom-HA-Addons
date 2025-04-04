import time
from typing import Callable, Dict, List, Optional

from bacpypes3.apdu import TimeSynchronizationRequest, UTCTimeSynchronizationRequest
from bacpypes3.basetypes import DateTime
from bacpypes3.errors import MissingRequiredParameter
from bacpypes3.pdu import Address, GlobalBroadcast
from bacpypes3.primitivedata import (
    BitString,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
)
from const import LOGGER

_debug = 0


def objectidentifier_alt_encode(value: ObjectIdentifier):
    return (value[0].attr, value[1])


def enumerated_alt_encode(value: Enumerated):
    return value.attr


def bitstring_alt_encode(value: BitString):
    return value


class DeviceConfiguration:
    device_identifier: ObjectIdentifier | str = "all"
    cov_lifetime: int | float = 600
    cov_items: list[ObjectIdentifier | str] = []
    poll_rate_quick: int | float = 60
    poll_items_quick: list[ObjectIdentifier | str] = []
    poll_rate_slow: int | float = 600
    poll_items_slow: list[ObjectIdentifier | str] = []
    resub_on_iam: bool = False
    reread_on_iam: bool = False

    def __init__(self, config: dict):
        self.device_identifier = config.get("deviceID", "all")
        self.cov_lifetime = config.get("CoV_lifetime", 600)
        self.cov_items = self._validate_object_list(config.get("CoV_list", []))
        self.poll_rate_quick = config.get("quick_poll_rate", 60)
        self.poll_items_quick = self._validate_object_list(
            config.get("quick_poll_list", [])
        )
        self.poll_rate_slow = config.get("slow_poll_rate", 600)
        self.poll_items_slow = self._validate_object_list(
            config.get("slow_poll_list", [])
        )
        self.resub_on_iam = config.get("resub_on_iam", False)
        self.reread_on_iam = config.get("reread_on_iam", False)

    def _validate_object_list(self, items):
        """Ensure all list items are either valid ObjectIdentifiers or 'all' as a string."""
        valid_items = []
        for item in items:
            if isinstance(item, ObjectIdentifier) or item == "all":
                valid_items.append(item)
            else:
                try:
                    valid_items.append(ObjectIdentifier(item))  # Attempt to convert
                except Exception:
                    LOGGER.warning(
                        f"Invalid object identifier in configuration: {item}"
                    )
        return valid_items

    def all_to_objects(self, object_list: list[ObjectIdentifier]):
        if self.cov_items == ["all"]:
            self.cov_items = object_list

        if self.poll_items_quick == ["all"]:
            self.poll_items_quick = object_list

        if self.poll_items_slow == ["all"]:
            self.poll_items_slow = object_list

    def remove_duplicate_slow_polls(self):
        """Remove non-unique identifiers from poll_items_slow if they exist in poll_items_quick."""
        quick_set = {
            ObjectIdentifier(item) for item in self.poll_items_quick
        }  # Convert quick poll list to a set for fast lookup
        self.poll_items_slow = [
            ObjectIdentifier(item)
            for item in self.poll_items_slow
            if ObjectIdentifier(item) not in quick_set
        ]

    def remove_duplicate_quick_polls(self):
        """Remove non-unique identifiers from poll_items_quick if they exist in cov_items."""
        cov_set = {
            ObjectIdentifier(item) for item in self.cov_items
        }  # Convert quick poll list to a set for fast lookup
        self.poll_items_quick = [
            ObjectIdentifier(item)
            for item in self.poll_items_quick
            if ObjectIdentifier(item) not in cov_set
        ]

    def to_dict(self):
        return {
            "deviceID": self.device_identifier,
            "CoV_lifetime": self.cov_lifetime,
            "CoV_list": self.cov_items,
            "quick_poll_rate": self.poll_rate_quick,
            "quick_poll_list": self.poll_items_quick,
            "slow_poll_rate": self.poll_rate_slow,
            "slow_poll_list": self.poll_items_slow,
            "resub_on_iam": self.resub_on_iam,
            "reread_on_iam": self.reread_on_iam,
        }

    def __repr__(self):
        return str(self.to_dict())


class TimeSynchronizationService:
    """Time synchronisation service"""

    _debug: Callable[..., None]

    def time_sync(
        self,
        date_time: Optional[DateTime] = None,
        address: Optional[Address] = None,
    ):
        """Generate time synchronization request"""
        # if self._debug:
        #    TimeSynchronizationService._debug("time_sync")

        time_sync_request = TimeSynchronizationRequest(
            destination=address or GlobalBroadcast()
        )

        if date_time is None:
            raise MissingRequiredParameter("missing time")

        date_time = DateTime(date_time)

        time_sync_request.time = date_time

        # if self._debug:
        #    TimeSynchronizationService._debug("    - time_sync: %r", time_sync_request)

        # function returns a finished future that can be ignored
        self.request(time_sync_request)

    def utc_time_sync(
        self,
        date_time: Optional[DateTime] = None,
        address: Optional[Address] = None,
    ):
        """Generate time synchronization request"""
        # if self._debug:
        #    TimeSynchronizationService._debug("time_sync")

        time_sync_request = UTCTimeSynchronizationRequest(
            destination=address or GlobalBroadcast()
        )

        if date_time is None:
            raise MissingRequiredParameter("missing time")

        date_time = DateTime(date_time)

        time_sync_request.time = date_time

        # if self._debug:
        #    TimeSynchronizationService._debug("    - time_sync: %r", time_sync_request)

        # function returns a finished future that can be ignored
        self.request(time_sync_request)
