# ==========================================================
# TRACE - NETWORK DISCOVERY - VERSION 0.015
# ==========================================================

# STEP 461: IMPORT REQUIRED LIBRARIES.

import ipaddress


# STEP 461A: CONFIGURE APPROVED DISCOVERY NETWORKS.
# Do not automatically scan every computer network adapter.

DISCOVERY_NETWORKS = [
    "192.168.1.0/24"
]


# STEP 461B: GENERATE VALID HOST ADDRESSES.

def get_discovery_addresses():

    addresses = []

    for subnet in DISCOVERY_NETWORKS:

        network = ipaddress.ip_network(
            subnet,
            strict=True
        )

        for address in network.hosts():
            addresses.append(str(address))

    return addresses

# STEP 462: DISCOVER ETHERNET/IP DEVICES.
# Use a bounded, read-only discovery operation.
# No SQL registration occurs during discovery.

from pycomm3 import CIPDriver


def discover_devices():

    print("TRACE: Scanning approved network...")

    devices = CIPDriver.discover(
        broadcast_address="192.168.1.255"
    )

    results = []

    for device in devices:

        ip_address = device.get("ip_address")
        product_name = device.get("product_name")
        product_type = device.get("product_type")

        # STEP 463: CAPTURE DEVICE IDENTITY FOR PLC QUALIFICATION.
        # Discovery remains read-only and does not modify SQL.

        results.append({
            "ip_address": ip_address,
            "product_name": product_name,
            "product_type": product_type,
            "vendor": device.get("vendor"),
            "product_code": device.get("product_code"),
            "serial": device.get("serial"),
            "revision": device.get("revision")
        })

    return results

# STEP 464: IDENTIFY DISCOVERED ROCKWELL PLCs.
# Reuse the existing Ethernet Monitor's identification function.
# Do not register anything in SQL during this test.

import importlib.util
from pathlib import Path


def identify_discovered_plcs(devices):

    # STEP 464A: LOAD THE EXISTING ETHERNET MONITOR.

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

    identified = []

    # STEP 464B: FILTER DISCOVERED DEVICES.

    for device in devices:

        if (
            device.get("vendor") !=
            "Rockwell Automation/Allen-Bradley"
        ):
            continue

        if (
            device.get("product_type") !=
            "Programmable Logic Controller"
        ):
            continue

        # STEP 464C: READ THE CONTROLLER'S PROGRAM NAME
        # AND PHYSICAL IDENTITY.

        try:
            identity = monitor.identify_controller(
                device["ip_address"]
            )

            identified.append(identity)

        except Exception as error:
            print(
                f"TRACE: Could not identify "
                f"{device['ip_address']}: {error}"
            )

    return identified

# STEP 465: SYNCHRONIZE DISCOVERED PLCs WITH SQL.
# Reuse the existing registration and serial-number tracking.
# Do not create a second registration mechanism.

def synchronize_discovered_plcs(controllers):

    monitor_path = (
        Path(__file__).resolve().parent
        / "V0.014_Ethernet_Monitor.py"
    )

    spec = importlib.util.spec_from_file_location(
        "trace_ethernet_monitor_sync",
        monitor_path
    )

    monitor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)

    results = []

    for controller in controllers:

        try:
            controller_id, action = monitor.register_controller(
                controller
            )

            results.append({
                "controller_id": controller_id,
                "controller_name": controller["controller_name"],
                "ip_address": controller["ip_address"],
                "serial_number": controller["serial_number"],
                "action": action
            })

            print(
                f"TRACE: Controller {controller_id} "
                f"successfully {action}."
            )

        except Exception as error:
            print(
                f"TRACE: Registration failed for "
                f"{controller['ip_address']}: {error}"
            )

    return results

# STEP 462A: TEST LIVE NETWORK DISCOVERY.

if __name__ == "__main__":

    addresses = get_discovery_addresses()

    print("TRACE Network Discovery")
    print("-----------------------")
    print("Configured networks:", DISCOVERY_NETWORKS)
    print("Total addresses:", len(addresses))

    try:
        devices = discover_devices()

        print("\nDiscovered devices:", len(devices))

        # STEP 463A: DISPLAY DISCOVERED DEVICE IDENTITIES.

        for device in devices:
            print("\nDiscovered device:")
            for field, value in device.items():
                print(f"  {field}: {value}")

            # STEP 464D: TEST PLC IDENTIFICATION AFTER DISCOVERY.

            print("\nTRACE - IDENTIFIED PLCs")
            print("-----------------------")

            controllers = identify_discovered_plcs(devices)

            for controller in controllers:
                print("IP Address:", controller["ip_address"])
                print("Controller Name:", controller["controller_name"])
                print("Serial Number:", controller["serial_number"])
                print("Firmware:", controller["firmware_major"])

                # STEP 465A: SYNCHRONIZE DISCOVERED PLCs WITH TRACE.

                print("\nTRACE - SQL INVENTORY SYNCHRONIZATION")
                print("-------------------------------------")

                synchronized = synchronize_discovered_plcs(controllers)

                for result in synchronized:
                    print(
                        f"Controller ID: {result['controller_id']} | "
                        f"Name: {result['controller_name']} | "
                        f"Action: {result['action']}"
                    )

    except Exception as error:
        print("Discovery failed:", error)