# STEP 247: READ THE CONTROLLER AUDIT VALUE.
# Read-only CIP request. No PLC writes.

from pycomm3 import CIPDriver, Services, ClassCode
import struct

PLC_IP = "192.168.1.1"


# STEP 247A: CONNECT TO THE CONTROLLER.
with CIPDriver(PLC_IP) as plc:

    # STEP 247B: REQUEST THE AUDIT VALUE.
    response = plc.generic_message(
        service=0x0E,
        class_code=0x8E,
        instance=1,
        attribute=0x1B,
        # STEP 248: USE A CONNECTED CIP REQUEST.
        connected=True,
        name="Audit Value Get",
    )

    # STEP 247C: CHECK THE RESPONSE.
    if response:
        print("TRACE - AUDIT VALUE RESPONSE")
        print("Raw value:", response.value)

        if isinstance(response.value, bytes) and len(response.value) == 8:
            low, high = struct.unpack("<II", response.value)
            print("DINT[0]:", low)
            print("DINT[1]:", high)
            print("Audit Value (HEX):", f"{high:08X}{low:08X}")
        else:
            print("Unexpected response format or length.")
    else:
        print("Audit Value request failed.")
        print("Error:", response.error)