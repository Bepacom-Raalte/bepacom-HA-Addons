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
1. Now you're free to use the add-on!


## API Points

You'll be able to find all API points at "homeassistant.local/docs" whereas homeassistant.local is your host name.
These points will allow you to read and write to the BACnet devices on the network.

- /apiv1/json								- Return a full list of all device data.
- /apiv1/command/whois						- Make the add-on do a Who Is request.
- /apiv1/command/iam						- Make the add-on do an I Am request.
- /apiv1/{deviceid}							- Retrieve all data from a specific device.
- /apiv1/{deviceid}{objectid}				- Retrieve all data from an object from a specific device.
- /apiv1/{deviceid}{objectid}{propertyid}	- Retrieve a property value from an object in a specific device.

These API points will be used as follows:
"homeassistant.local/apiv1/json"

**Device Identifiers** get written as "device:number", so if a device has an identifier of 100, the notation for API will be "device:100".

The same applies to **Object Identifiers**. The object name will be camelCase. An example notation for an AnalogInput 1 would be "analogInput:1".

**Property Identifiers** also apply camelCase logic. An object identifier will be written as "objectIdentifier". 
Fortunately, you only need to write the value for writing properties.


## Configuration

**Note**: _Remember to restart the add-on when the configuration is changed._

Example add-on configuration:

```yaml
log_level: info
seconds_between_quotes: 5
```

### Option: `Object Name`

### Option: `Interface IP`

### Option: `Object ID`

### Option: `Maximum APDU Length Accepted`

### Option: `Segmentation Supported`

### Option: `Vendor Identifier`

### Option: `BACnet/IP Broadcast Management Device`

### Option: `Max Segments Accepted`




## Credits

**Bepacom B.V. Raalte**


[![Open this add-on in your Home Assistant instance.][bepacom-badge]][bepacom]


**Windesheim Zwolle Elektrotechniek**


[![Open this add-on in your Home Assistant instance.][windesheim-badge]][windesheim]


[addon-badge]: https://my.home-assistant.io/badges/supervisor_addon.svg
[addon]: https://my.home-assistant.io/redirect/supervisor_addon/?addon=13b6b180_bacnetinterface&repository_url=https%3A%2F%2Fgithub.com%2FGravySeal%2Fbepacom-repo
[bepacom-badge]: https://www.bepacom.nl/wp-content/uploads/2018/09/logo-bepacom-besturingstechniek.jpg
[bepacom]: https://www.bepacom.nl/
[windesheim-badge]: https://www.windesheim.nl/getmedia/d06bfafc-febf-4c5e-bcec-bdf619d2ae93/Windesheim_logo.png
[windesheim]: https://www.windesheim.nl/