
# ==========================================================
# TRACE - HARDWARE REPLACEMENT DETECTION TEST
# Uses a synthetic controller identity.
# Does not communicate with or modify a physical PLC.
# ==========================================================

# STEP 1: IMPORT THE ETHERNET MONITOR.
import importlib.util
from pathlib import Path


# STEP 2: LOAD THE EXISTING MONITOR MODULE.
monitor_path = (
    Path(__file__).resolve().parent
    / "V0.014_Ethernet_Monitor.py"
)

spec = importlib.util.spec_from_file_location(
    "trace_ethernet_monitor",
    monitor_path
)

monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


# STEP 3: CREATE A FICTIONAL REPLACEMENT PROCESSOR.
# Use the existing equipment IP but a synthetic serial.
# This test does not call identify_controller().

test_identity = {
    "ip_address": "192.168.1.1",
    "controller_name": "Synthetic Test Processor",
    "plc_model": "1769-L30ER/A",
    "controller_family": "CompactLogix",
    "firmware_major": 30,
    "firmware_minor": 11,
    "serial_number": "TRACE_SYNTHETIC_REPLACEMENT_TEST",
}


# STEP 4: TEST THE REPLACEMENT DETECTION.
try:
    controller_id, action = monitor.register_controller(
        test_identity
    )

    print("Unexpected registration:", controller_id, action)

except ValueError as error:
    print("TRACE detection result:")
    print(error)


# STEP 5: TEST THE SAME IDENTITY AGAIN.
# Repeated detection should not create another pending event.

try:
    monitor.register_controller(test_identity)

except ValueError as error:
    print("\nRepeated detection result:")
    print(error)
