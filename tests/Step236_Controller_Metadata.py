# STEP 236: INSPECT AVAILABLE CONTROLLER METADATA.
# Read-only. No PLC writes.

from pycomm3 import LogixDriver
from pprint import pprint

PLC_IP = "192.168.1.1"

# STEP 236A: CONNECT TO THE PLC.
with LogixDriver(PLC_IP) as plc:

    # STEP 236B: DISPLAY AVAILABLE CONTROLLER METADATA.
    print("TRACE - CONTROLLER METADATA")
    pprint(plc.info)

    # STEP 236C: DISPLAY THE CONTROLLER NAME.
    print("\nTRACE - CONTROLLER NAME")
    print(plc.name)

print("\nPASS: Controller metadata inspection completed.")
