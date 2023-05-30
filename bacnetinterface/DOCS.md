# Bepacom EcoPanel BACnet/IP interface

This add-on is created by Bepacom B.V. for their EcoPanel. 

The goal is to add BACnet functionality to Home Assistant so these devices can be displayed on the dashboard.

This add-on works on Home Assistant OS as well as Home Assistant Supervised.


## Installation

1. Click the Home Assistant My button below to open the add-on on your Home
   Assistant instance.

   [![Open this add-on in your Home Assistant instance.][addon-badge]][addon]

1. Click the "Install" button to install the add-on.
1. Start the "Bepacom EcoPanel BACnet/IP Interface" add-on.
1. Check the logs of the "Bepacom EcoPanel BACnet/IP Interface" add-on to see if everything went
   well.
1. Now your Home Assistant device is a virtual BACnet/IP device!


## API Points

You'll be able to find all API points in the Web UI. All outside access to the API and Web UI is blocked. 
Only through Home Assistant the API can be accessed. 
This means the integration is allowed to communicate while the rest is not.

These points will allow you to GET data:

- /apiv1/json								- Return a full list of all device data.
- /apiv1/command/whois						- Make the add-on do a Who Is request.
- /apiv1/command/iam						- Make the add-on do an I Am request.
- /apiv1/command/readall					- Make the add-on read everything
- /apiv1/{deviceid}							- Retrieve all data from a specific device.
- /apiv1/{deviceid}{objectid}				- Retrieve all data from an object from a specific device.
- /apiv1/{deviceid}{objectid}{propertyid}	- Retrieve a property value from an object in a specific device.

These points will allow you to POST data:
- /apiv1/{deviceid}{objectid}				- Write to an object from a specific device.
- /apiv1/subscribe/{deviceid}{objectid}		- Subscribe to an object from a specific device.


**Device Identifiers** get written as "device:number", so if a device has an identifier of 100, the notation for API will be "device:100".

**Object Identifiers** apply the same notation. The object name will be camelCase. An example notation for an AnalogInput 1 would be "analogInput:1".

**Property Identifiers** also apply camelCase logic. An object identifier will be written as "objectIdentifier". 
Fortunately, you only need to write the value for writing properties.


## Configuration

**Note**: _Remember to restart the add-on when the configuration is changed._

Example add-on configuration:

```yaml
objectName: EcoPanel
address: 0.0.0.0/24
objectIdentifier: 420
defaultPriority: 15
loglevel: WARNING
maxApduLenghtAccepted: 1024
segmentationSupported: segmentedBoth
vendorID: 15
maxSegmentsAccepted: 16
```

### Option: `objectName`
The Object Name that this device will get. This will be seen by other devices on the BACnet network.

### Option: `address`
The address of the BACnet interface. 0.0.0.0/24 is recommended as it'll bind to all available IP addresses.
Best is to write the IP of the Ethernet port connected to the BACneet network. Include /24 as not all BACnet devices can be detected without.

### Option: `objectIdentifier`
The Object Identifier that this device will get. This will be seen by other devices on the BACnet network. **Make sure it's unique!**

### Option: 'defaultPriority'
The priority your write requests get. Low number means high priority. High number means low priority. Recommended to keep at 15 or 16 unless you know what higher priority can do to your BACnet devices.

### Option: "loglevel"
The verbosity of the logs in the add-on. Usually WARNING is alright, INFO gets a little chatty.

### Option: `maxApduLenghtAccepted`
The max length an APDU can be before it'll be rejected. Recommended to leave the default value if you don't know what it does.

### Option: `segmentationSupported`
Whether segmentation is supported by the interface. Recommended to leave as is, because there's a lot of data from most devices that can't be received in one message.

### Option: `vendorID`
Identifier of the vendor of the interface. As we don't have an official identifier, put anything you want in here.

### Option: `foreignBBMD`
The address of a BBMD device. Not implemented.

### Option: `foreignTTL`
The Time To Live for BBMD packets. Not implemented.

### Option: `maxSegmentsAccepted`
The maximum amount of segments that'll be accepted by the interface.


## Credits

**Bepacom B.V. Raalte**


[![Open this add-on in your Home Assistant instance.][bepacom-badge]][bepacom]


[addon-badge]: https://my.home-assistant.io/badges/supervisor_addon.svg
[addon]: https://my.home-assistant.io/redirect/supervisor_addon/?addon=13b6b180_bacnetinterface&repository_url=https%3A%2F%2Fgithub.com%2FGravySeal%2Fbepacom-repo
[bepacom-badge]: https://www.bepacom.nl/wp-content/uploads/2018/09/logo-bepacom-besturingstechniek.jpg
[bepacom]: https://www.bepacom.nl/
