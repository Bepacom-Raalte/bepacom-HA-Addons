devicelist = [("device",0),("device",1),("device",2)]
objectlist = [("analogValue",0), ("analogValue",1),("binaryValue",0)]
devices = dict()

# Objects die ik wil ondersteunen
# AnalogInput, AnalogOutput, AnalogValue, BinaryInput, BinaryOutput, BinaryValue, 
# MultiStateInput, MultiStateOutput, MultiStateValue, Device, LargeAnalogValue,
# IntegerValue, PositiveIntegerValue

BACnet_object = {
    "objectIdentifier": None,
    "objectName": None,
    "objectType": None,
    "presentValue": None,
    "description": None,
    "reliability": None,
    "outOfService": None,
    "units": None,
    "notificationClass": None 
    }

device = {
    "objectIdentifier": None,
    "objectName": None,
    "objectType": None,
    "systemStatus": None,
    "vendorName": None,
    "vendorIdentifier": None,
    "modelName": None,
    "firmwareRevision": None,
    "applicationSoftwareVersion": None,
    "protocolVersion": None,
    "protocolRevision": None,
    "protocolServicesSupported": None,
    "protocolObjectTypesSupported": None,
    "objectList": dict(),
    "maxApduLengthAccepted": None,
    "segmentationSupported": None,
    "apduSegmentTimeout": None,
    "apduTimeout": None,
    "numberOfApduRetries": None,
    "deviceAddressBinding": None,
    "databaseRevision": None
    }


for entry in devicelist:
    devices.update({str(entry[0])+":"+str(entry[1]): device})


for x,y in devices.items():
    for object in objectlist:
        y["objectList"].update({str(object[0])+ ":" +str(object[1]): BACnet_object})
    print(x,y)


#for object in objectlist:
#    device["objectlist"].update({str(object[0])+ ":" +str(object[1]): BACnet_object})

#print(device)

