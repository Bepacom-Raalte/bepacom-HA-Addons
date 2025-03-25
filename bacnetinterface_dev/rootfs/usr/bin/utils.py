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

_debug = 0


def objectidentifier_alt_encode(value: ObjectIdentifier):
    return (value[0].attr, value[1])


def enumerated_alt_encode(value: Enumerated):
    return value.attr


def bitstring_alt_encode(value: BitString):
    return value


def format_identifier(identifier: ObjectIdentifier):
    return f"{identifier[0]}:{identifier[1]}"


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
