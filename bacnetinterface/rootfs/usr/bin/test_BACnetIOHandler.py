import pytest
from BACnetIOHandler import BACnetIOHandler


def test_update_object():
    handler = BACnetIOHandler()
    objectID = ("analogInput", 1)
    deviceID = ("device", 1)
    new_val = {"presentValue": 100}
    handler.update_object(objectID, deviceID, new_val)
    assert handler.BACnetDeviceDict[deviceID][objectID]["presentValue"] == 100


def test_addr_to_dev_id():
    handler = BACnetIOHandler()
    address = ("192.168.0.1", 47808)
    deviceID = ("device", 1)
    handler.BACnetDeviceDict[deviceID] = {"address": address}
    assert handler.addr_to_dev_id(address) == deviceID


def test_dev_id_to_addr():
    handler = BACnetIOHandler()
    address = ("192.168.0.1", 47808)
    deviceID = ("device", 1)
    handler.BACnetDeviceDict[deviceID] = {"address": address}
    assert handler.dev_id_to_addr(deviceID) == address


def test_assign_id():
    handler = BACnetIOHandler()
    obj = ("device", 1)
    id1 = handler.assign_id(obj)
    id2 = handler.assign_id(obj)
    assert id1 == id2
