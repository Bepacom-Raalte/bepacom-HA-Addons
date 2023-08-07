<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

# 1.1.1
7/8/2023
- Subscriptions no longer indefinite as some devices don't support it.
- Subscriptions can be deleted through the UI.
- Subscriptions get renewed automatically.


# 1.1.0

7/8/2023
- NGINX now waits until the API is available before starting.
- Copied CoV method of legacy version. This will stop the system from being overwhelmed and hanging.
- NGINX using templates to dynamically add own IP.


# 1.0.6

10/7/2023
- Configuration options are now dropdown menu's, reducing configuration page clutter.
- Fixed segmentation issue, segmentation now gets passed down to requests.
- Removed the "fall back" functionality where the add-on reads every object of the object list seperately.
- Punched a hole in NGINX to allow the device's own IP to communicate with the API.


# 1.0.5

10/7/2023
- segmentation-not-supported error while reading objectlist solved.
- Allowing more internal Home Assistant IP's.


# 1.0.4

10/7/2023
- Base image to hassio-addons/addon-base-python image.
- Library versions are more closely guarded now.
- Added segmentation option back in.
- Trying to log abort PDU's. Issue with Priva devices not supporting segmentation.
- Reading objectList last to get most info from the device without getting an error.


# 1.0.3

29/6/2023
- EDE files give out correct data through API now.
- Increased sleeping time during startup to give the add-on enough chance to catch all BACnet data.


# 1.0.2

28/6/2023
- Fixed an issue where empty websockets would remain in memory.
- CoV is now indefinite, because of lack of lifetime. Siemens PXC4 doesn't work with lifetime = 0.
- Removed excessive logging.


# 1.0.1

20/6/2023
- Updated web UI main page to make navigation a little easier.
- Unsubscribing now gets done when the add-on closes.
- All errors now really should be caught instead of dumping tracelogs.
- Updated translations.
- EDE files show up on the web UI now once uploaded.


# 1.0.0

16/06/2023
- Rewrote the backbones of the program. Now using BACpypes3 instead of BACpypes.
- Removed certain configuration options that have no effect.
- New API points!
- Subscription page on the web UI now functions like the EDE page where you can add or remove subscriptions easily.
- CIDR notation gets discovered when using "auto" as ip address setting.
- Can configure the rate at which all objects get updated.
- Catching more errors so the logs don't get spammed with trace logs.
- This update _may_ break a thing or two. Please make an Issue on GitHub to get it solved.


## 0.2.1

01/06/2023
- Rounding of long float values. It's now rounding at the first decimal.
- LAN IP detection still works automatically, and only shuts down if it's automatic in config. If it's not auto, you can manually write an IP and not shut down.
- Add-on uses image from GitHub now, decreasing install time.
- fixed presentvalue not doing anything for EDE files


## 0.2.0

01/06/2023
- Added commissioning API points!
- Now it's possible to load EDE files in the add-on.
- This allows the integration generate placeholder entities in Home Assistant until the real device gets connected to the network.
- EDE files that have been loaded can be deleted.
- A restart of the add-on will remove the EDE files from the add-on.
- Web UI pages allow easy adding and removing.


## 0.1.6

30/05/2023
- Bumped Alpine base image to 3.18.
- Python version is now 3.11.
- Packages on GitHub renamed to bacnet-interface instead of null.


## 0.1.5

11/05/2023
- Updated web UI page to include Redoc API documentation.
- Viewing API documentation works now.
- API documentation now uses ingress.
- Made loglevel a mandatory configuration.


## 0.1.4

09/05/2023
- Updated configuration to include Write Request Priority.
- Updated DOCS to reflect the change.
- We appreciate the feedback!!


## 0.1.3

12/4/2023
- Readme updated to include integration.
- NGINX now blocks everything from outside.
- Trying to automatically get the ethernet adapter from the host device.
- FastAPI to include lifetime now instead of on_startup().


## 0.1.2

16/02/2023
- Dutch translations added.
- Log level can be adjusted. Defaults to WARNING now.
- Read request every 60 seconds asking for values that can change, instead of asking for static values. This reduces network traffic.
- WebUI has tooltips now. Buttons or fields should explain what they do.


## 0.1.1

15/02/2023
- Bumped up FastAPI to version 0.92.0 for security reasons.
- Restructured S6-overlay processes. One shots for initialisations, longruns for actual processes.
- Discovery enabled for if it's possible to discovery integration in the future.
- Added automatic ethernet adapter detection. Won't work in every case, but it'll help a lot of people out.
- BACnet subscriptions now have a lifetime instead of none. Increases compatability.
- BACnet subscriptions last maximum time and get resubscribed every 60 seconds along with a read request.
- Websockets can handle multiple clients now.
- Configuration of the add-on has been simplified.
- Added some API tests internally.
- API has an endpoint that let's you subscribe now.
- Flask no longer included, FastAPI handles everything now, along with uvicorn.
- WebUI gets updated over websocket. This means values are the same as in the API.
- WebUI can write now as well.
- WebUI has gotten a makeover in general.
- WebUI Subscription page can actually subscribe now.
- This add-on runs on Raspberry Pi 3 as it would on an Intel NUC. This means Raspberry Pi is supported.


# 0.1.0

10/1/2022
- API now has more datatypes
- objectIdentifier, statusFlags became list.
- notificationClass added as object as well as a property to access through API.
- Multi State stateText and numberOfStates have been added.
- Attempting to get min and max presentValue's from objects now.
- Altered webUI page to be a little functional. It has 3 buttons you can press to call a service like I Am or Who Is.
- Formatting of code now uses Black and Isort.
- Removed unused packages from Dockerfile: 'nmap' and 'iproute2'.
- Added a read all command, so all devices can be read again on command.
- Bumped version to '0.1.0' as the add-on ready to be used.


## 0.0.5

02/01/2023
- Added write functionality through API
- Added multiple API points. You can find them through going to /docs
- Who Is and I Am can be received and sent through host network. This is possible through Home Assistant Supervised
- Add-on is now matching requirements for this project. Error handling etc. will be improved later, as will code optimisations.


## 0.0.4

21/12/2022
- Zeroconf removed, not functional for add-on. If this was a core add-on, would be using DHCP.
- FastAPI running on a separate thread
- Created BACnetIOHandler class to serve as BACnet application
- BACnet devices will automatically be subscribed to
- FastAPI program converts the BACnet dictionary it gets from BACnetIOHandler to a bite sized dictionary containing only the essentials for Home Assistant
- API can do get request on /apiv1/json
- Can connect to websocket on ws://ip:port/ws
- Websocket will automatically push updates on Change Of Value
- Changed icon to Bepacom logo


## 0.0.3

07/11/2022
- Added FastAPI to function as API in the future
- Changed webserver to Uvicorn
- Changed program to split into multiple files
- BACnet device can be detected
- WebUI can be loaded, it's just an example page now
- API and web UI are split into different paths, /apiv1/ and /webapp/
- Zeroconf added, unsure if functioning


## 0.0.2

31/10/2022
- WhoIsIAmProgram Running
- Nginx set up to work correctly with Flask webserver
- Flask and BACpypes happily working together <3


## 0.0.1

 21/10/2022
- Getting started...
