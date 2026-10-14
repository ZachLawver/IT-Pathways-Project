# STEP 235: READ LIVE LOGIX CONTROLLER INFORMATION.
# Read-only. No program changes or PLC writes.

from pycomm3 import LogixDriver
from pprint import pprint

PLC_IP = "192.168.1.1"


# STEP 235A: CONNECT TO THE CONTROLLER.
with LogixDriver(PLC_IP) as plc:

    # STEP 235B: READ CONTROLLER INFORMATION.
    information = plc.get_plc_info()

    # STEP 235C: DISPLAY THE RESPONSE.
    print("TRACE - LIVE LOGIX CONTROLLER INFORMATION")
    pprint(information)

print("PASS: Controller information request completed.")