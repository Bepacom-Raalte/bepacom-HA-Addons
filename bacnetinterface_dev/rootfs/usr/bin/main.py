"""Main script for EcoPanel BACnet add-on."""

import asyncio
import configparser
import ipaddress
import json
import os
import socket
from datetime import datetime
from logging import Formatter, Logger, StreamHandler, getLogger
from logging.handlers import RotatingFileHandler
from typing import TypeVar

import psutil
import uvicorn
import webAPI
from BACnetIOHandler import BACnetIOHandler, ObjectManager
from bacpypes3.apdu import AbortPDU, ErrorPDU, RejectPDU
from bacpypes3.basetypes import Null, ObjectType, Segmentation, ServicesSupported
from bacpypes3.ipv4.app import Application
from bacpypes3.local.device import DeviceObject
from bacpypes3.pdu import IPv4Address
from bacpypes3.primitivedata import ObjectIdentifier
from const import LOGGER, subscribable_objects
from webAPI import app as fastapi_app

KeyType = TypeVar("KeyType")


def exception_handler(loop, context):
	"""Handle uncaught exceptions"""
	try:
		LOGGER.exception(f'An uncaught error occurred: {context["exception"]}')
	except:
		LOGGER.error("Tried to log error, but something went horribly wrong!!!")


def get_ip_and_netmask():
	for iface, addrs in psutil.net_if_addrs().items():
		if iface.startswith(("enp", "eth", "eno")):
			for addr in addrs:
				if addr.family == socket.AF_INET:
					return addr.address, addr.netmask
	return None, None


def ip_prefix_by_netmask(netmask):
	return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen


def get_auto_ip() -> str:

	ipaddr, netmask = get_ip_and_netmask()

	if ipaddr:
		cidr = ip_prefix_by_netmask(netmask)

	else:
		print(
			"Warning: No suitable ethernet adapters found. You probably won't detect anything now."
		)
		ipaddr = socket.gethostbyname(socket.gethostname())
		cidr = "24"

	LOGGER.debug(f"{ipaddr}/{cidr}")

	return f"{ipaddr}/{cidr}"


async def updater_task(app: Application, interval: int, event: asyncio.Event) -> None:
	"""Task to handle periodic updates to the BACnet dictionary"""
	try:
		while True:
			await event.wait()
			for device_id in app.bacnet_device_dict:
				services_supported = app.bacnet_device_dict[device_id][device_id].get(
					"protocolServicesSupported", ServicesSupported()
				)
				if services_supported["read-property-multiple"] == 1:
					await app.read_multiple_objects_periodically(
						device_identifier=device_id
					)
				else:
					await app.read_objects_periodically(device_identifier=device_id)
			event.clear()

	except asyncio.CancelledError as err:
		LOGGER.warning(f"Updater task cancelled: {err}")


async def writer_task(
	app: Application, write_queue: asyncio.Queue, default_write_prio: int
) -> None:
	"""Task to handle the write queue"""
	try:
		while True:
			queue_result = await write_queue.get()
			device_id = queue_result[0]
			object_id = queue_result[1]
			property_id = queue_result[2]
			property_val = queue_result[3]
			array_index = queue_result[4]
			priority = queue_result[5]

			if not priority:
				priority = default_write_prio

			if property_val == None:
				property_val = Null("null")

			LOGGER.debug(
				f"Writing: {device_id}, {object_id}, {property_id}, {property_val}, {priority}"
			)

			try:
				response = await app.write_property(
					address=app.dev_to_addr(device_id),
					objid=object_id,
					prop=property_id,
					value=property_val,
					array_index=array_index,
					priority=priority,
				)
			except (AbortPDU, ErrorPDU, RejectPDU) as err:
				LOGGER.error(f"response: {err}")
				continue
			except Exception as err:
				LOGGER.error(f"response: {err}")
				continue

			LOGGER.info(f"response: {response if response else 'Acknowledged'}")

			await asyncio.sleep(0.1)

			read = await app.read_property(
				address=app.dev_to_addr(device_id),
				objid=object_id,
				prop=property_id,
				array_index=array_index,
			)
			LOGGER.info(f"Write result: {read}")

			app.dict_updater(
				device_identifier=device_id,
				object_identifier=object_id,
				property_identifier=property_id,
				property_value=property_val,
			)

	except Exception as err:
		LOGGER.error(f" Writer task error: {err}")
	except asyncio.CancelledError as err:
		LOGGER.warning(f"Writer task cancelled: {err}")


async def subscribe_handler_task(app: Application, sub_queue: asyncio.Queue) -> None:
	"""Task to handle the subscribe queue"""
	try:
		while True:
			queue_result = await sub_queue.get()
			device_identifier = queue_result[0]
			object_identifier = queue_result[1]
			notifications = queue_result[2]
			lifetime = queue_result[3]

			task_name = f"{device_identifier[0].attr}:{device_identifier[1]},{object_identifier[0].attr}:{object_identifier[1]}"

			for task in app.subscription_tasks:
				if task_name in task.get_name():
					LOGGER.error(
						f"Subscription for {device_identifier}, {object_identifier} already exists"
					)
					break
			else:
				await app.create_subscription_task(
					device_identifier=device_identifier,
					object_identifier=object_identifier,
					confirmed_notifications=notifications,
					lifetime=lifetime,
				)

	except asyncio.CancelledError as err:
		LOGGER.warning(f"Subscribe task cancelled: {err}")


async def unsubscribe_handler_task(
	app: Application, unsub_queue: asyncio.Queue
) -> None:
	"""Task to handle the unsubscribe queue"""
	try:
		while True:
			queue_result = await unsub_queue.get()
			device_identifier = queue_result[0]
			object_identifier = queue_result[1]

			task_name = f"{device_identifier[0].attr}:{device_identifier[1]},{object_identifier[0].attr}:{object_identifier[1]}"

			for task in app.subscription_tasks:
				if task_name in task.get_name():
					task.cancel()
					break
			else:
				LOGGER.error("Subscription task does not exist")

	except asyncio.CancelledError as err:
		LOGGER.warning(f"Unsubscribe task cancelled: {err}")


def get_configuration() -> tuple:
	try:
		with open("/data/options.json") as f:
			options = json.load(f)
	except Exception as err:
		LOGGER.warning(f"No options.json detected! {err}")
		options = {
			"subscriptions": {
				"analogInput": True,
				"analogOutput": True,
				"analogValue": True,
				"binaryInput": True,
				"binaryOutput": True,
				"binaryValue": True,
				"multiStateInput": True,
				"multiStateOutput": True,
				"multiStateValue": True,
			}
		}

	try:
		with open("/usr/bin/auth_token.ini", "r") as auth_token:
			token = auth_token.read()
	except Exception as err:
		LOGGER.warning(f"No Token received! {err}")
		token = None

	default_write_prio = options.get("defaultPriority", 15)

	loglevel = options.get("loglevel", "INFO")

	ipv4_address = options.get("address", None)

	if ipv4_address == "auto":
		ipv4_address = get_auto_ip()

	if not ipv4_address:
		ipv4_address = input("BACnet IP Address as *x.x.x.x/24*: ")

	ipv4_address = IPv4Address(ipv4_address)

	object_identifier = options.get("objectIdentifier", 60)

	object_name = options.get("objectName", "EcoPanel")

	vendor_id = options.get("vendorIdentifier", 15)

	segmentation_supported = options.get("segmentation", Segmentation.noSegmentation)

	max_apdu = options.get("maxApduLengthAccepted", 480)

	max_segments = options.get("maxSegmentsAccepted", 64)

	foreign_ip = options.get("foreignBBMD", None)

	foreign_ttl = options.get("foreignTTL", 255)

	update_interval = options.get("updateInterval", 60)

	return (
		default_write_prio,
		loglevel,
		ipv4_address,
		object_identifier,
		object_name,
		vendor_id,
		segmentation_supported,
		max_apdu,
		max_segments,
		foreign_ip,
		foreign_ttl,
		update_interval,
		options,
		token,
	)


async def main():
	"""Main function of the application."""

	loop = asyncio.get_event_loop()

	loop.set_exception_handler(exception_handler)

	(
		default_write_prio,
		loglevel,
		ipv4_address,
		object_identifier,
		object_name,
		vendor_id,
		segmentation_supported,
		max_apdu,
		max_segments,
		foreign_ip,
		foreign_ttl,
		update_interval,
		options,
		token,
	) = get_configuration()

	formatter = Formatter(
		"[%(asctime)-8s]|%(levelname)-8s |%(filename)-18s->%(funcName)-36s: %(message)s",
		datefmt="%H:%M:%S",
	)

	path_str = os.path.dirname(os.path.realpath(__file__))

	date_var = datetime.now().date()

	log_path = f"{path_str}/bacnet_addon-{date_var}.log"

	webAPI.log_path = log_path

	file_handler = RotatingFileHandler(
		filename=log_path, mode="w", maxBytes=15 * 1024 * 1024, backupCount=2
	)

	file_handler.setFormatter(formatter)

	file_handler.setLevel("DEBUG")

	LOGGER.addHandler(file_handler)

	stream_handler = StreamHandler()

	stream_handler.setFormatter(formatter)

	stream_handler.setLevel(loglevel)

	LOGGER.addHandler(stream_handler)

	LOGGER.setLevel("DEBUG")

	LOGGER.debug(
		f"Starting with settings: ID = {object_identifier}, Name = {object_name}, IP = {ipv4_address}, max apdu = {max_apdu}, max segments = {max_segments}, segmentation = {segmentation_supported}, foreign IP = {foreign_ip}, log level = {loglevel}"
	)

	this_device = DeviceObject(
		objectIdentifier=ObjectIdentifier(f"device,{object_identifier}"),
		objectName=object_name,
		description="BACnet Add-on for Home Assistant",
		vendorIdentifier=int(vendor_id),
		segmentationSupported=Segmentation(segmentation_supported),
		maxApduLengthAccepted=int(max_apdu),
		maxSegmentsAccepted=int(max_segments),
	)

	if foreign_ip == "-":
		foreign_ip = None

	app = BACnetIOHandler(
		device=this_device,
		local_ip=ipv4_address,
		foreign_ip=foreign_ip,
		ttl=int(foreign_ttl),
		update_event=webAPI.events.val_updated_event,
		addon_device_config=options.get("devices_setup"),
	)

	object_manager = ObjectManager(
		app=app, entity_list=options.get("entity_list", None), api_token=token
	)

	app.asap.maxApduLengthAccepted = int(max_apdu)

	app.asap.segmentationSupported = Segmentation(segmentation_supported)

	app.asap.maxSegmentsAccepted = int(max_segments)

	app.subscription_list = subscribable_objects

	update_task = asyncio.create_task(
		updater_task(
			app=app,
			interval=int(500),
			event=webAPI.events.read_event,
		)
	)

	write_task = asyncio.create_task(
		writer_task(
			app=app,
			write_queue=webAPI.events.write_queue,
			default_write_prio=default_write_prio,
		)
	)

	sub_task = asyncio.create_task(
		subscribe_handler_task(app=app, sub_queue=webAPI.events.sub_queue)
	)

	unsub_task = asyncio.create_task(
		unsubscribe_handler_task(app=app, unsub_queue=webAPI.events.unsub_queue)
	)

	webAPI.sub_list = app.subscription_tasks
	webAPI.bacnet_device_dict = app.bacnet_device_dict
	webAPI.bacnet_application = app
	webAPI.who_is_func = app.who_is
	webAPI.i_am_func = app.i_am
	webAPI.events.startup_complete_event = app.startup_complete

	if loglevel == "DEBUG":
		uvilog = "info"
	else:
		uvilog = loglevel.lower()

	config = uvicorn.Config(
		app=fastapi_app, host="127.0.0.1", port=7813, log_level=uvilog, log_config=None
	)

	server = uvicorn.Server(config)

	await server.serve()

	if app:
		update_task.cancel()
		write_task.cancel()
		sub_task.cancel()
		unsub_task.cancel()
		await app.end_subscription_tasks()
		app.close()


if __name__ == "__main__":
	asyncio.run(main())
