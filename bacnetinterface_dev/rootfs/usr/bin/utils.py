from bacpypes3.primitivedata import BitString, Enumerated, ObjectIdentifier


def objectidentifier_alt_encode(value: ObjectIdentifier):
	return (value[0].attr, value[1])


def enumerated_alt_encode(value: Enumerated):
	return value.attr


def bitstring_alt_encode(value: BitString):
	return value
