"""
run_knee_in_motionsolve.py — the knee FMU's first drive in the real deck.
Clones a PROVEN scenario run (AVLlit tip-in 50%), swaps the motor FMU seat:
stock Motor_PMSM_dual (ModelExchange) -> GeorgeEMS_Champion (CoSimulation),
patches only the three strings that must change, and runs MotionSolve
headless exactly the way pipeline.py does. Everything else - tires, driver,
ADF, suspension, logging requests - is byte-identical: a controlled
experiment on the EMS alone (Bible Ch.29).
"""
import os
import re
import shutil
import subprocess
import sys

SRC = DATA_ROOT + r"\avl_regenoff_runs\AVLlit_tipin_50pct_20260726_075106"
DECK = "AVLlit_tipin_50pct.xml"
FMU = r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Champion.fmu"
BAT = r"C:\Program Files\Altair\2025\hwsolvers\scripts\motionsolve.bat"
RUN = os.path.join(os.environ["TEMP"], "champion_ms_run")

os.makedirs(RUN, exist_ok=True)
for f in (DECK, "custom_event_tipout_10.adf"):
    shutil.copy(os.path.join(SRC, f), RUN)
shutil.copy(FMU, os.path.join(RUN, "GeorgeEMS_Champion.fmu"))

deck_path = os.path.join(RUN, DECK)
text = open(deck_path, encoding="utf-8", errors="replace").read()

# 1. FMU path (the motor seat only - it is the only string ending in
#    Motor_PMSM_dual.fmu)
new_fmu = os.path.join(RUN, "GeorgeEMS_Champion.fmu").replace("\\", "/")
text, n1 = re.subn(r'"[^"]*Motor_PMSM_dual\.fmu"', '"' + new_fmu + '"', text)

# 2. Mode string: ONLY the motor FMU's string entity (-535050562)
pat = r'(id\s*=\s*"-535050562"\s*\n\s*string\s*=\s*")ModelExchange(")'
text, n2 = re.subn(pat, r'\1CoSimulation\2', text)

# 3. ADF path -> the run folder copy (keep the driver identical)
adf_new = os.path.join(RUN, "custom_event_tipout_10.adf").replace("\\", "/")
text, n3 = re.subn(r'"[^"]*custom_event_tipout_10\.adf"', '"' + adf_new + '"', text)

open(deck_path, "w", encoding="utf-8").write(text)
print(f"deck patched: fmu_path x{n1}, mode x{n2}, adf x{n3}")
if n1 != 1 or n2 != 1:
    sys.exit("PATCH COUNTS WRONG - aborting before solver launch")

# solver env: deck-referenced dll folders on PATH (pipeline._solver_env logic)
env = os.environ.copy()
dirs = []
for m in re.finditer(r'"([A-Za-z]:[^"]+?\.dll)"', text, re.IGNORECASE):
    d = os.path.dirname(m.group(1).replace("/", os.sep))
    if os.path.isdir(d) and d not in dirs:
        dirs.append(d)
env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
print(f"solver PATH prepended with {len(dirs)} usersub dirs")

proc = subprocess.Popen([BAT, DECK], cwd=RUN, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, errors="replace", bufsize=1)
for line in proc.stdout:
    line = line.rstrip()
    if line and ("Time" in line or "ERROR" in line or "Error" in line
                 or "WARNING" in line.upper() or "FMU" in line):
        print(line, flush=True)
rc = proc.wait()
print("solver exit:", rc)
print("run dir:", RUN)
