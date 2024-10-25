from typing import Dict
from pydantic import BaseModel

class SubscriptionData(BaseModel):
	confirmation: str
	lifetime: int
	lifetime_remaining: float

# Model for a device, where the keys (object types) are dynamic (analogInput, analogValue, etc.)
class SubscriptionObjectData(BaseModel):
	__root__: Dict[str, SubscriptionData]
	
# Top-level model to handle multiple devices, where device keys are dynamic
class SubscriptionDeviceData(BaseModel):
	__root__: Dict[str, SubscriptionObjectData]
	
	class Config:
		schema_extra = {
			"examples" : [
				{
					"device:10": {
						"analogInput:0": {
							"confirmation": "confirmed",
							"lifetime": 60,
							"lifetime_remaining": 46.7
						}
					}
				},
			]
		}
		
class PropertyData(BaseModel):
	__root: Dict[str, int | float | bool | str]
	
	class Config:
		schema_extra = {
			"examples" : [
				{
					"presentValue" : 21.4,
				},
			]
		}

# Model for a device, where the keys (object types) are dynamic (analogInput, analogValue, etc.)
class ObjectData(BaseModel):
	__root__: Dict[str, PropertyData]
		
class DeviceData(BaseModel):
	__root__: Dict[str, ObjectData]
	
	class Config:
		schema_extra = {
			"examples" : [
				{
					"device:1": {
						"analogInput:0": {
							"presentValue" : 12,
							"outOfService" : False,
							"objectIdentifier": ["analogInput", 0]
						}
					}
				},
			]
		}