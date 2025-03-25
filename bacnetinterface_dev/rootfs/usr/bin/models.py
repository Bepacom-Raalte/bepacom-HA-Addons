from typing import Dict

from pydantic import BaseModel, RootModel


class SubscriptionData(BaseModel):
    confirmation: str
    lifetime: int
    lifetime_remaining: float


# Model for a device, where the keys (object types) are dynamic (analogInput, analogValue, etc.)
class SubscriptionObjectData(RootModel):
    root: Dict[str, SubscriptionData]


# Top-level model to handle multiple devices, where device keys are dynamic
class SubscriptionDeviceData(RootModel):
    root: Dict[str, SubscriptionObjectData]

    class Config:
        schema_extra = {
            "examples": [
                {
                    "device:10": {
                        "analogInput:0": {
                            "confirmation": "confirmed",
                            "lifetime": 60,
                            "lifetime_remaining": 46.7,
                        }
                    }
                },
            ]
        }


# Model for property data
class PropertyData(RootModel):
    root: Dict[str, int | float | bool | str]

    class Config:
        schema_extra = {
            "examples": [
                {
                    "presentValue": 21.4,
                },
            ]
        }


# Model for a device, where the keys (object types) are dynamic (analogInput, analogValue, etc.)
class ObjectData(RootModel):
    root: Dict[str, PropertyData]


class DeviceData(RootModel):
    root: Dict[str, ObjectData]

    class Config:
        schema_extra = {
            "examples": [
                {
                    "device:1": {
                        "analogInput:0": {
                            "presentValue": 12,
                            "outOfService": False,
                            "objectIdentifier": ["analogInput", 0],
                        }
                    }
                },
            ]
        }
