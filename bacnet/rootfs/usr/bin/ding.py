devicelist = [("device",0),("device",1),("device",2)]
objectlist = [("analogValue",0), ("analogValue",1),("binaryValue",0)]
devices = dict()

BACnet_object = {
    "object_identifier": None,
    "object_name": None,
    "object_type": None,
    "present_value": None,
    "description": None,
    "reliability": None,
    "out_of_service": None,
    "units": None,
    "notification_class": None 
    }

device = {
    "object_identifier": None,
    "object_name": None,
    "object_type": None,
    "system_status": None,
    "vendor_name": None,
    "vendor_identifier": None,
    "model_name": None,
    "firmware revision": None,
    "application_software_version": None,
    "protocol_version": None,
    "protocol_revision": None,
    "protocol_services_supported": None,
    "protocol_object_types_supported": None,
    "objectlist": dict(),
    "max_apdu_length_accepted": None,
    "segmentation_supported": None,
    "apdu_segment_timeout": None,
    "apdu_timeout": None,
    "number_of_apdu_retries": None,
    "device_address_binding": None,
    "database_revision": None
    }


for entry in devicelist:
    devices.update({str(entry[0])+":"+str(entry[1]): device})

#print(devices)

for x,y in devices.items():
    for object in objectlist:
        y["objectlist"].update({str(object[0])+ ":" +str(object[1]): BACnet_object})
    print(x,y)


#for object in objectlist:
#    device["objectlist"].update({str(object[0])+ ":" +str(object[1]): BACnet_object})

#print(device)

