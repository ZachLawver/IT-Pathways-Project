

# STEP 1: Import subnet validation tools.
import ipaddress



# STEP 2: Configure approved discovery networks.
DISCOVERY_NETWORKS = [
    "192.168.1.0/24"
]



# STEP 3: Generate usable host addresses.
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


# STEP 4: Import EtherNet/IP discovery support.
from pycomm3 import CIPDriver


# STEP 5: Start read-only device discovery.
def discover_devices():

    print("TRACE: Scanning approved networks...")

    results = []
    seen_addresses = set()

    for subnet in DISCOVERY_NETWORKS:

        # STEP 6: Calculate each configured subnet's broadcast address.
        network = ipaddress.ip_network(subnet, strict=True)
        broadcast = str(network.broadcast_address)

        print(f"TRACE: Discovering devices on {subnet}")

        devices = CIPDriver.discover(
            broadcast_address=broadcast
        )

        # STEP 7: Filter device responses by IP address.
        for device in devices:

            ip_address = device.get("ip_address")

            if not ip_address or ip_address in seen_addresses:
                continue

            if ipaddress.ip_address(ip_address) not in network:
                continue

            seen_addresses.add(ip_address)

            results.append({
                "ip_address": ip_address,
                "product_name": device.get("product_name"),
                "product_type": device.get("product_type"),
                "vendor": device.get("vendor"),
                "product_code": device.get("product_code"),
                "serial": device.get("serial"),
                "revision": device.get("revision")
            })

    return results


import importlib.util
from pathlib import Path


# STEP 8: Identify qualifying Rockwell controllers.
def identify_discovered_plcs(devices):


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


# STEP 9: Register identified controllers in SQL.
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


# STEP 10: Run standalone discovery and display results.
if __name__ == "__main__":

    addresses = get_discovery_addresses()

    print("TRACE Network Discovery")
    print("-----------------------")
    print("Configured networks:", DISCOVERY_NETWORKS)
    print("Total addresses:", len(addresses))

    try:
        devices = discover_devices()

        print("\nDiscovered devices:", len(devices))

        for device in devices:
            print("\nDiscovered device:")
            for field, value in device.items():
                print(f"  {field}: {value}")

        print("\nTRACE - IDENTIFIED PLCs")
        print("-----------------------")

        # STEP 11: Identify controllers once per discovery cycle.
        controllers = identify_discovered_plcs(devices)

        for controller in controllers:
            print("IP Address:", controller["ip_address"])
            print("Controller Name:", controller["controller_name"])
            print("Serial Number:", controller["serial_number"])
            print("Firmware:", controller["firmware_major"])

        print("\nTRACE - SQL INVENTORY SYNCHRONIZATION")
        print("-------------------------------------")

        # STEP 12: Synchronize controllers once per discovery cycle.
        synchronized = synchronize_discovered_plcs(controllers)

        for result in synchronized:
            print(
                f"Controller ID: {result['controller_id']} | "
                f"Name: {result['controller_name']} | "
                f"Action: {result['action']}"
            )

    except Exception as error:
        print("Discovery failed:", error)
