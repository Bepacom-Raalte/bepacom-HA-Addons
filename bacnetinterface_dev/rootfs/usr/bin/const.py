import logging

from bacpypes3.basetypes import ObjectType, PropertyIdentifier

LOGGER = logging.getLogger(__package__)

device_properties_to_read: list = [
    PropertyIdentifier("objectIdentifier"),
    PropertyIdentifier("objectType"),
    PropertyIdentifier("objectName"),
    PropertyIdentifier("systemStatus"),
    PropertyIdentifier("vendorName"),
    PropertyIdentifier("vendorIdentifier"),
    PropertyIdentifier("description"),
    PropertyIdentifier("modelName"),
    PropertyIdentifier("firmwareRevision"),
    PropertyIdentifier("applicationSoftwareVersion"),
    PropertyIdentifier("protocolVersion"),
    PropertyIdentifier("protocolRevision"),
    PropertyIdentifier("protocolServicesSupported"),
    PropertyIdentifier("protocolObjectTypesSupported"),
    PropertyIdentifier("segmentationSupported"),
    PropertyIdentifier("apduTimeout"),
    PropertyIdentifier("numberOfApduRetries"),
    PropertyIdentifier("databaseRevision"),
    PropertyIdentifier("segmentationSupported"),
    PropertyIdentifier("maxApduLengthAccepted"),
    PropertyIdentifier("maxSegmentsAccepted"),
    PropertyIdentifier("objectList"),
    PropertyIdentifier("serialNumber"),
]

object_properties_to_read_once: list = [
    PropertyIdentifier("objectIdentifier"),
    PropertyIdentifier("objectType"),
    PropertyIdentifier("objectName"),
    PropertyIdentifier("description"),
    PropertyIdentifier("presentValue"),
    PropertyIdentifier("statusFlags"),
    PropertyIdentifier("outOfService"),
    PropertyIdentifier("units"),
    PropertyIdentifier("eventState"),
    PropertyIdentifier("reliability"),
    PropertyIdentifier("covIncrement"),
    PropertyIdentifier("stateText"),
    PropertyIdentifier("numberOfStates"),
    PropertyIdentifier("notificationClass"),
    PropertyIdentifier("minPresValue"),
    PropertyIdentifier("maxPresValue"),
    PropertyIdentifier("activeText"),
    PropertyIdentifier("inactiveText"),
    PropertyIdentifier("polarity"),
    PropertyIdentifier("relinquishDefault"),
    PropertyIdentifier("resolution"),
]

object_properties_to_read_periodically: list = [
    PropertyIdentifier("presentValue"),
    PropertyIdentifier("statusFlags"),
    PropertyIdentifier("outOfService"),
    PropertyIdentifier("eventState"),
    PropertyIdentifier("reliability"),
    PropertyIdentifier("covIncrement"),
]

subscribable_objects: list = [
    ObjectType("accumulator"),
    ObjectType("analogValue"),
    ObjectType("analogInput"),
    ObjectType("analogOutput"),
    ObjectType("binaryValue"),
    ObjectType("binaryInput"),
    ObjectType("binaryOutput"),
    ObjectType("multiStateValue"),
    ObjectType("multiStateInput"),
    ObjectType("multiStateOutput"),
    ObjectType("alertEnrollment"),
    ObjectType("eventEnrollment"),
    ObjectType("integerValue"),
    ObjectType("calendar"),
    ObjectType("pulseConverter"),
    ObjectType("program"),
    ObjectType("largeAnalogValue"),
    ObjectType("positiveIntegerValue"),
    ObjectType("lightingOutput"),
]
