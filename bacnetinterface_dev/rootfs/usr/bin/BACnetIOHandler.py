import asyncio
import logging
import traceback
import json
import requests
from math import isinf, isnan
from typing import Any, Dict, TypeVar

from bacpypes3.apdu import (AbortPDU, ConfirmedCOVNotificationRequest,
							ErrorPDU, ErrorRejectAbortNack, ReadPropertyACK,
							ReadPropertyRequest, RejectPDU, SimpleAckPDU,
							SubscribeCOVRequest, WritePropertyRequest)
from bacpypes3.basetypes import (BinaryPV, DeviceStatus, EngineeringUnits,
								 ErrorType, EventState, PropertyIdentifier,
								 Reliability)
from bacpypes3.constructeddata import AnyAtomic, Array, List, SequenceOf
from bacpypes3.errors import *
from bacpypes3.ipv4.app import ForeignApplication, NormalApplication
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.binary import BinaryValueObject
from bacpypes3.local.analog import AnalogValueObject
from bacpypes3.object import get_vendor_info
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import (BitString, Date, Null, ObjectIdentifier,
									 ObjectType, Time, Unsigned)
from const import (device_properties_to_read, object_properties_to_read_once,
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
		"""Refreshing subscriptions automatically."""  # Maybe make a blacklist to exclude objects we dont want to subscribe to.
		while True:
			await asyncio.sleep(self.default_subscription_lifetime)
			logging.info("Refreshing subscriptions...")
			for task in self.subscription_tasks:
				await self.create_subscription_task(
					device_identifier=task[4],
					object_identifier=task[1],
					confirmed_notifications=task[2],
					lifetime=task[3],
				)

	async def do_WhoIsRequest(self, apdu) -> None:
		"""Handle incoming Who Is request."""
		logging.info(f"Received Who Is Request from {apdu.pduSource}")
		await super().do_WhoIsRequest(apdu)

	async def do_IAmRequest(self, apdu) -> None:
		"""Handle incoming I Am request."""

		logging.info(f"I Am from {apdu.iAmDeviceIdentifier}")

		if apdu.iAmDeviceIdentifier[1] in self.device_info_cache.instance_cache:
			logging.debug(f"Device {apdu.iAmDeviceIdentifier} already in cache!")
			in_cache = True
		else:
			await self.device_info_cache.set_device_info(apdu)
			in_cache = False
			
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
			logging.warning(
				f"Abort PDU error while reading device properties: {device_identifier}: {err}"
			)

			if not "segmentation-not-supported" in str(err):
				return False
			else:
				await self.read_device_props_non_segmented(apdu)

		except ErrorRejectAbortNack as err:
			logging.error(
				f"Nack error reading device props: {device_identifier}: {err}"
			)
		except AttributeError as err:
			logging.error(
				f"Attribute error reading device props: {device_identifier}: {err}"
			)
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

	async def read_device_props_non_segmented(self, apdu):
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
				logging.error(
					f"Abort PDU error while reading device properties without segmentation: {device_identifier}: {err}"
				)
			except ErrorRejectAbortNack as err:
				logging.error(
					f"Nack error reading device props non segmented: {device_identifier}: {err}"
				)
			except AttributeError as err:
				logging.error(
					f"Attribute error reading device props non segmented: {err}"
				)
			except ValueError as err:
				logging.error(f"ValueError reading device props non segmented: {err}")
			except Exception as err:
				logging.error(f"Exception reading device props non segmented: {err}")
			else:
				if response and response is not ErrorType:
					self.dict_updater(
						device_identifier=device_identifier,
						object_identifier=device_identifier,
						property_identifier=property_id,
						property_value=response,
					)

		object_amount = await self.read_property(
			address=address,
			objid=device_identifier,
			prop=PropertyIdentifier("objectList"),
			array_index=0,
		)

		object_list = []

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

	async def read_object_list(self, device_identifier):
		"""Read all objects from a device."""
		logging.info(f"Reading objectList from {device_identifier}...")
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
				logging.warning(
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
					if property_value and property_value is not ErrorType:
						self.dict_updater(
							device_identifier=device_identifier,
							object_identifier=object_identifier,
							property_identifier=property_identifier,
							property_value=property_value,
						)

	async def read_object_list_non_segmented(self, device_identifier):
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
					response = await self.read_property(
						address=self.dev_to_addr(device_identifier),
						objid=device_identifier,
						prop=property_id,
					)

					if response and response is not ErrorType:
						self.dict_updater(
							device_identifier=device_identifier,
							object_identifier=device_identifier,
							property_identifier=property_id,
							property_value=response,
						)

		except AbortPDU as err:
			logging.error(
				f"Abort PDU error while reading device object list without segmentation: {device_identifier}: {err}"
			)
		except ErrorRejectAbortNack as err:
			logging.error(f"Nack error: {device_identifier}: {err}")
		except AttributeError as err:
			logging.error(f"Attribute error: {err}")

	async def read_objects_periodically(self):
		"""Read objects after a set time."""
		logging.info(f"Periodic object reading...")
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
					logging.warning(f"Abort PDU Error: {obj_id}: {err}")

					if not "segmentation-not-supported" in str(err):
						return False
					else:
						await self.read_objects_non_segmented(device_identifier)

				except ErrorRejectAbortNack as err:
					logging.error(
						f"Nack error reading objects periodically: {obj_id}: {err}"
					)

				except AttributeError as err:
					logging.error(f"Attribute error: {obj_id}: {err}")

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

	async def read_objects_non_segmented(self, device_identifier):
		"""Read objects if regular way failed."""
		logging.info(f"Reading objects non segmented for {device_identifier}...")
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

			try:
				for property_id in object_properties_to_read_periodically:
					response = await self.read_property(
						address=self.dev_to_addr(device_identifier),
						objid=obj_id,
						prop=property_id,
					)

					if response:
						self.dict_updater(
							device_identifier=device_identifier,
							object_identifier=obj_id,
							property_identifier=property_id,
							property_value=response,
						)
			except AbortPDU as err:
				logging.error(f"Abort PDU Error: {obj_id}: {err}")

			except ErrorRejectAbortNack as err:
				logging.error(f"Nack error: {obj_id}: {err}")

			except AttributeError as err:
				logging.error(f"Attribute error: {obj_id}: {err}")

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
			logging.info(
				f"Subscribing to: {device_identifier}, {object_identifier}... response: {response}"
			)

		except (ErrorRejectAbortNack, RejectException, AbortException) as error:
			logging.error(
				f"Error while subscribing to {device_identifier}, {object_identifier}: {error}"
			)
			return
		except (AbortPDU, ErrorPDU, RejectPDU) as error:
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
					logging.warning(
						f"NoneType property: {apdu.monitoredObjectIdentifier[0]} {value.propertyIdentifier} {value.value}"
					)
					continue
				elif value.propertyIdentifier not in object_properties_to_read_once:
					logging.warning(
						f"Ignoring property: {apdu.monitoredObjectIdentifier[0]} {value.propertyIdentifier} {value.value}"
					)
					continue
				else:
					property_value = value.value.cast_out(property_type)

				logging.debug(
					f"COV: {apdu.initiatingDeviceIdentifier}, {apdu.monitoredObjectIdentifier}, {value.propertyIdentifier}, {property_value}"
				)

				self.dict_updater(
					device_identifier=apdu.initiatingDeviceIdentifier,
					object_identifier=apdu.monitoredObjectIdentifier,
					property_identifier=value.propertyIdentifier,
					property_value=property_value,
				)

		except Exception as err:
			logging.error(
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
			logging.warning(
				f"{self.addr_to_dev(apdu.pduSource)} tried to read {apdu.objectIdentifier} {apdu.propertyIdentifier}: {err}"
			)

	async def do_WritePropertyRequest(self, apdu: WritePropertyRequest):
		try:
			# await super().do_WritePropertyRequest(apdu)

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
			
			if apdu.propertyIdentifier == PropertyIdentifier("presentValue"):
				await self.write_to_api_queue.put((obj_id, property_type, array_index, priority, property_value))

				self.write_to_api.set()

				while self.write_to_api.is_set():
					await asyncio.sleep(0.1)
				
				response = await self.write_to_api_queue.get()

				if not response:
					# Reject
					resp = ErrorPDU(context=apdu)

					# return the result
					await self.response(resp)
			
					logging.warning("Rejected write!")
				
				else:
					# Acknowledge
					resp = SimpleAckPDU(context=apdu)

					# return the result
					await self.response(resp)
			
					logging.warning("Ack'd write!")
					
			elif apdu.propertyIdentifier == PropertyIdentifier("covIncrement"):
				
				await obj.write_property(
					apdu.propertyIdentifier, property_value, array_index, priority
				)

				# success
				resp = SimpleAckPDU(context=apdu)

				# return the result
				await self.response(resp)
			
			else:
				resp = ErrorPDU(context=apdu)

				# return the result
				await self.response(resp)
			
				logging.warning("Rejected write!")
		
		except Exception as err:
			logging.exception(f"Something went wrong while getting object written! {apdu.pduSource}")
			

class ObjectManager():
	"""Manages BACpypes3 application objects."""
	
	binary_entity_ids = []
	analog_entity_ids = []
	
	def __init__(self, app: BACnetIOHandler, objects_to_create: dict, api_token: str, interval: int = 5):
		"""Initialize objects."""
		self.app = app
		self.api_token = api_token
		self.interval = interval
		
		self.services = self.fetch_services()
		
		for entityID in objects_to_create['binaryValue']:
			if entityID.get('entityID'):
				self.binary_entity_ids.append(entityID.get('entityID'))
				
		for entityID in objects_to_create['analogValue']:
			if entityID.get('entityID'):
				self.analog_entity_ids.append(entityID.get('entityID'))
		
		for index, entity in enumerate(self.binary_entity_ids):
			data = self.fetch_entity_data(entity)
			self.add_object(object_type="binaryValue", index=index, entity=data)
			
		for index, entity in enumerate(self.analog_entity_ids):
			data = self.fetch_entity_data(entity)
			self.add_object(object_type="analogValue", index=index, entity=data)
			
		asyncio.create_task(
			self.data_update_task(interval=self.interval)
		)
		
		asyncio.create_task(
			self.data_write_task()
		)
		

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
			logging.error(f"Failed to get {entity_id}. {response.status_code}")
			return False
		
		
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
			logging.error(f"Failed to get {entity_id}. {response.status_code}")
			return False
		

	def post_services(self, entity_id, value):
		"""Write value to API."""
		
		split_id = entity_id.split(".")

		domain = split_id[0]
		
		data = {"entity_id": f"{entity_id}"}
		
		if domain in ("number", "input_number", "counter" ):
			service = "set_value"
			data.update({"value": value})
		elif domain in ("switch", "light", "camera", "climate", "water_heater", "media_player", "input_boolean"):
			service = "turn_on" if value else "turn_off"
		else:
			logging.error(f"Can not write to {entity_id}")
			return False	

		url = f"http://supervisor/core/api/services/{domain}/{service}"
		headers = {
			"Authorization": f"Bearer {self.api_token}",
			"content-type": "application/json",
		}

		response = requests.post(url, headers=headers, json=data)
		
		logging.error(url)
		
		logging.error(domain)
	
		if response.status_code == 200:
			return json.loads(response.text)
		else:
			logging.error(f"Failed to post {entity_id}: HTTP Code {response.status_code}")
			return False
		
	
	def add_object(self, object_type: str ,index: int, entity: dict):
		"""Add object to application"""
		if object_type == "binaryValue":
			bin_val_obj = BinaryValueObject(
				objectIdentifier=f"binaryValue,{index}",
				objectName=entity["attributes"].get("friendly_name"),
				presentValue= True if entity.get("state").lower() == "on" else False,
				description=f"Home Assistant entity {entity["attributes"].get("friendly_name")}",
				# statusFlags=[0, 0, 0, 0],  # inAlarm, fault, overridden, outOfService
				eventState=EventState.normal,
				outOfService=False,
				)
			self.app.add_object(bin_val_obj)
			
		if object_type == "analogValue":
			
			units = self.determine_units(entity["attributes"].get("unit_of_measurement")) if entity["attributes"].get("unit_of_measurement") is not None else None
			
			ana_val_obj = AnalogValueObject(
				objectIdentifier=f"analogValue,{index}",
				objectName=entity["attributes"].get("friendly_name"),
				presentValue= entity.get("state"),
				description=f"Home Assistant entity {entity["attributes"].get("friendly_name")}",
				# statusFlags=[0, 0, 0, 0],  # inAlarm, fault, overridden, outOfService
				eventState=EventState.normal,
				outOfService=False,
				covIncrement=0.1,
				units=units
				)
			self.app.add_object(ana_val_obj)
			
			
	def determine_units(self, unit):
		"""EngineeringUnits for objects from Home Assistant units"""
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
		else:
			bacnetUnits = None
		return bacnetUnits

			
	def update_object(self, object_type, index, entity):
		"""Update objects with API data."""
		
		obj = self.app.get_object_id(ObjectIdentifier(str(object_type + ":" + str(index))))
		
		prop = PropertyIdentifier("presentValue")
		
		if object_type == BinaryValueObject or object_type == "binaryValue":
			value = True if entity.get("state").lower() == "on" else False
			
		elif object_type == AnalogValueObject or object_type == "analogValue":
			value = entity.get("state")
		
		setattr(obj, prop.attr, value)

			
	async def data_update_task(self, interval: int = 5):
		"""Updater task to update objects with fresh data."""
		try:
			while True:
				try:
					await asyncio.wait_for(asyncio.sleep(interval+1), timeout=interval)
				except asyncio.TimeoutError:
					
					for index, entity in enumerate(self.binary_entity_ids):
						data = self.fetch_entity_data(entity)
						self.update_object(object_type="binaryValue", index=index, entity=data)
						
					for index, entity in enumerate(self.analog_entity_ids):
						data = self.fetch_entity_data(entity)
						self.update_object(object_type="analogValue", index=index, entity=data)

		except asyncio.CancelledError as err:
			logging.warning(f"data_update_task cancelled: {err}")
			

	async def data_write_task(self):
		"""Updater task to write data to Home Assistant."""
		try:
			while True:
				
				await self.app.write_to_api.wait()
				
				obj, property_type, array_index, priority, property_value = await self.app.write_to_api_queue.get()
				
				entity_index = obj[1]

				if obj[0].attr == "binaryValue":
					entity_id = self.binary_entity_ids[entity_index]
				elif obj[0].attr == "analogValue":
					entity_id = self.analog_entity_ids[entity_index]
				else:
					entity_id = None
					
				write_response = self.post_services(entity_id=entity_id, value=property_value)
				
				self.app.write_to_api.clear()
				
				if write_response:
					self.update_object(object_type=obj[0].attr, index=entity_index, entity=write_response[0])
					await self.app.write_to_api_queue.put(True)
				else:
					await self.app.write_to_api_queue.put(False)

		except asyncio.CancelledError as err:
			logging.warning(f"data_update_task cancelled: {err}")		