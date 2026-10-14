#Proof of Concept Extracting information from L5X 
#pathlib locates our file.
#ElementTree reads XML without additional installations.
#re searches ladder logic for specific instructions.

from pathlib import Path
import xml.etree.ElementTree as ET
import re

#Read the exported L5X file and find the controller.
project_file = Path(__file__).resolve().parent / "VPIII_PLC.L5X"
tree = ET.parse(project_file)
root = tree.getroot()

controller = root.find("Controller")

if controller is None:
    raise ValueError("No controller found in the L5X file")

print("CONTROLLER:", controller.get("Name"))
print("PROCESSOR:", controller.get("ProcessorType"))

#Walk through the controller's program structure
#Only inspect routines belonging to the controller programs

programs = controller.findall("./Programs/Program")

total_routines = 0
total_rungs = 0
afi_locations = []

for program in programs:
    program_name = program.get("Name")

    routines = program.findall("./Routines/Routine")
    total_routines += len(routines)
    for routine in routines:
        routine_name = routine.get("Name")
        rungs = routine.findall("./RLLContent/Rung")
        total_rungs += len(rungs)
        #Find AFI instructions in rung text.
        #Save the exact program, routine, and rung number
        for rung in rungs:
            rung_number = rung.get("Number")
            logic= rung.findtext("Text", default="")
            if re.search(r"\bAFI\s*\(", logic, re.IGNORECASE):
                afi_locations.append((program_name, routine_name, rung_number))

#Show project toals and the locations of AFI instructions.
print("\nPROJECT SUMMARY")
print("Programs:", len(programs))
print("Routines:", total_routines)
print("Ladder rungs:", total_rungs)

print("\nAFI INSTRUCTIONS FOUND:", len(afi_locations))
for program, routine, rung in afi_locations:
    print(f"{program} / {routine} / Rung {rung}")
