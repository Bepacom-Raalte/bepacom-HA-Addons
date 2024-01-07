# Bepacom EcoPanel BACnet/IP interface

The Bepacom EcoPanel BACnet/IP interface add-on is intended to be a bridge between the BACnet/IP network and Home Assistant.

The goal of this add-on is to add BACnet functionality to Home Assistant so these devices can be displayed on the dashboard.

This add-on works on Home Assistant OS as well as Home Assistant Supervised.

Created and maintained by [Bepacom B.V. Raalte](https://www.bepacom.nl/)


## Installation

1. Click the Home Assistant button below to open the add-on on your Home
   Assistant instance.

   [![Open this add-on in your Home Assistant instance.][addon-badge]][addon]

1. Click the "Install" button to install the add-on.
1. Start the "Bepacom EcoPanel BACnet/IP Interface" add-on.
1. Check the logs of the "Bepacom EcoPanel BACnet/IP Interface" add-on to see if everything went
   well.
1. Now your Home Assistant host is a virtual BACnet/IP device!


## API Points

You'll be able to find all API points in the Web UI. All outside access to the API and Web UI is blocked. 
Only through Home Assistant the API can be accessed. 
This means everything inside Home Assistant is allowed to communicate with the add-on while other devices are not.

### API V1

**Device Identifiers** get written as "device:number", so if a device has an identifier of 100, the notation for API will be "device:100".

**Object Identifiers** apply the same notation. The object name will be camelCase. An example notation for an AnalogInput 1 would be "analogInput:1".

**Property Identifiers** also apply camelCase logic. An object identifier will be written as "objectIdentifier". 
Fortunately, you only need to write the value for writing properties.

#### GET

- /apiv1/json								- Return a full list of all device data.
- /apiv1/command/whois						- Make the add-on do a Who Is request.
- /apiv1/command/iam						- Make the add-on do an I Am request.
- /apiv1/command/readall					- Make the add-on read everything.
- /apiv1/commission/ede					    - Read uploaded EDE files.
- /apiv1/{deviceid}							- Retrieve all data from a specific device.
- /apiv1/{deviceid}/{objectid}				- Retrieve all data from an object from a specific device.
- /apiv1/{deviceid}/{objectid}/{propertyid}	- Retrieve a property value from an object in a specific device.

#### POST

- /apiv1/commission/ede						- Post EDE files
- /apiv1/{deviceid}/{objectid}				- Write data to be written to a BACnet object
- /apiv1/subscribe/{deviceid}/{objectid}	- Upload an EDE file

#### DELETE

- /apiv1/commission/ede						- Remove an EDE file with the corresponding device identifier
- /apiv1/subscribe/{deviceid}/{objectid}	- Remove a CoV subscription

### API V2

API V2 is in progress and improves the usability of the add-on.

#### POST

- /apiv1/{deviceid}/{objectid}/{propertyid}	- Write a property value to an object in a specific device.


## Configuration

**Note**: _Remember to restart the add-on when the configuration is changed._

Example add-on configuration:

```yaml
objectName: EcoPanel
address: 192.168.2.11/24
objectIdentifier: 420
defaultPriority: 15
updateInterval: 60
subscriptions:
  analogInput: true
  analogOutput: true
  analogValue: true
  binaryInput: true
  binaryOutput: true
  binaryValue: true
  multiStateInput: false
  multiStateOutput: false
  multiStateValue: false
entity_list:
  - input_number.coolnumber
  - sensor.incomfort_cv_pressure
  - input_boolean.cooltoggle
loglevel: WARNING
segmentation: segmentedBoth
vendorID: 15
```

### Option: `Device Name`
The Object Name that this device will get. This will be seen by other devices on the BACnet network.

### Option: `Interface IP`
The address of the BACnet/IP interface.
You can write the IP yourself or use "auto" to let the add-on automatically try to get the right IP address.
If you want to write your IP manually, don't forget to put the CIDR behind the IP. For example: 192.168.2.11/24.
If you use subnet mask of 255.255.255.0, just put /24 behind your IP address.

### Option: `Device ID`
The Object Identifier that this device will get. This will be seen by other devices on the BACnet network. **Make sure it's unique in your network!**

### Option: `BACnet write priority`
The priority your write requests get. 
Low number means high priority. 
High number means low priority. 
Recommended to keep at 15 or 16 unless you know what a higher priority can do to your BACnet devices.

### Option: `Level of logging`
The verbosity of the logs in the add-on. 
There are 5 levels of logging:
- DEBUG: You'll get too much info. Only useful for development.
- INFO: You'll receive a lot of info that could be useful for troubleshooting.
- WARNING: You'll only receive logs if something went wrong.
- ERROR: You'll only see errors pop up.
- CRITICAL: You want to ignore everything that's happening.

Usually WARNING is sufficient.

### Option: `Update Interval`
The time after which the interface will try to read all object properties of each detected device again.

### Option: `CoV Subscriptions`
The types of objects you want to automatically subscribe to with a CoV subscription. 
Per object you can set true or false. 
Objects not included here don't get subscribed to.

```yaml
analogInput: true
analogOutput: true
analogValue: true
binaryInput: true
binaryOutput: true
binaryValue: true
multiStateInput: false
multiStateOutput: false
multiStateValue: false
```

### Option: `Home Assistant API Pollrate`
Pollrate in seconds to the Home Assistant API. This is to get data for the following 2 options. Recommended to not set it too fast.
This determines how fast the device's objects update their presentValue property.

### Option: `Entities to BACnet objects`
The entity ID's of what entities you want to make available as a BACnet objects. 
Keeping it empty will result in no additional objects next to your virtual device on the BACnet network.

Entities resulting in Analog Input object type:
- "sensor" if it's a numerical sensor.

Entities resulting in Analog Value object type:
- "number"
- "input_number"
- "counter"

Entities resulting in Binary Input object type:
- "binary_sensor"
- "schedule"

Entities resulting in Binary Value object type:
- "switch"
- "input_boolean"
- "light"

Entities resulting in Character String Value object type:
- "sensor" if it's a string.

The order of entities determines the object identifier of the entity, starting at object 0.
All the -Value objects can be written to!

Plans to include "climate", "water_heater", "media_player" and "vacuum" as supported entity types in the future.

### Option: `BACnet/IP Broadcast Management Device Address`
If you have your BACnet/IP network on another subnet, write the IP of your BBMD device here. This way, the add-on can communicate with the BBMD.
Otherwise keep this option empty.

### Option: `Foreign TTL`
Time To Live of foreign packets.

### Option: `Vendor Identifier`
Identifier of the vendor of the interface. As we don't have an official identifier, put anything you want in here.

### Option: `Segmentation Supported`
Segmentation type of the add-on. Recommended to leave on SegmentedBoth for the best compatibility.


## Credits

**Bepacom B.V. Raalte**


[![Open this add-on in your Home Assistant instance.][bepacom-badge]][bepacom]


[addon-badge]: https://my.home-assistant.io/badges/supervisor_addon.svg
[addon]: https://my.home-assistant.io/redirect/supervisor_addon/?addon=13b6b180_bacnetinterface&repository_url=https%3A%2F%2Fgithub.com%2FGravySeal%2Fbepacom-repo
[bepacom-badge]: https://www.bepacom.nl/wp-content/uploads/2018/09/logo-bepacom-besturingstechniek.jpg
[bepacom]: https://www.bepacom.nl/
