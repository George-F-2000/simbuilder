"""ride_height_static.py - static ride-height check of the healed deck with
patched coil-spring preloads (Bible 30.21: the car sits on its rear jounce
bumpers at rest and 19 mm from the front ones; the front tyres leave the
road in a 50% tip-in). Runs a 1.5 s brake-held hold (initial static + 1 ms
dynamic) and reports wheel-centre z vs design, bumper forces, tyre loads.
Usage: python ride_height_static.py <front_preload_N> <rear_preload_N> [front_k] [rear_k] [tag]"""
import json as _j, os as _o
_lc = {}
try:
    _lc = _j.load(open(_o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), 'vehicle_local.json')))
except Exception:
    pass
DATA_ROOT = _lc.get('data_root', 'C:/demo_data')

import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import plt_reader
from plant_repairs import apply_springs

SRC = DATA_ROOT + "/avl_regenoff_runs/AVLlit_tipin_50pct_20260726_075106"
DECK = "AVLlit_tipin_50pct.xml"
BAT = r"C:\Program Files\Altair\2025\hwsolvers\scripts\motionsolve.bat"
CHAMP = r"C:\Users\George\OneDrive\Desktop\PhD Thesis\Simulink EMS\GeorgeEMS_Champion.fmu"
FRONT_LEN, REAR_LEN = "141.06519", "156.4289"      # the deck's two coil-spring free lengths (front / rear)


def main():
    front, rear = float(sys.argv[1]), float(sys.argv[2])
    fk = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "-" else None
    rk = float(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] != "-" else None
    tag = sys.argv[5] if len(sys.argv) > 5 else "static"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run = os.path.join(DATA_ROOT, "healed_runs", "_static", f"{tag}_f{front:.0f}_r{rear:.0f}_k{fk or 0:.0f}_{rk or 0:.0f}_{stamp}")
    os.makedirs(run, exist_ok=True)
    for f in (DECK, "AVLlit_tipin_50pct.nam"):
        shutil.copy(os.path.join(SRC, f), run)
    shutil.copy(CHAMP, run)
    # 1.5 s brake-held hold at 1 ms, open loop
    adf = open(os.path.join(HERE, "sweep", "sweep_brake.adf"), encoding="utf-8", errors="replace").read()
    head = adf[:adf.index("[MANEUVERS_LIST]")]
    m1 = re.search(r"\$-+MANEUVER_1\s*\n.*?(?=\$-+MANEUVER_2\s*\n)", adf, re.S).group(0)
    tail = adf[re.search(r"\$-+OL_STEER\s*\n\[OL_STEER\]", adf).start():]
    adf1 = (head + "$" + "-"*70 + "MANEUVERS_LIST\n[MANEUVERS_LIST]\n{name            simulation_time      h_max           print_interval }\n"
            "'MANEUVER_1'     1.5                  0.001           0.01            \n" + m1 + tail)
    open(os.path.join(run, "static_hold.adf"), "w", encoding="utf-8").write(adf1)
    deck_path = os.path.join(run, DECK)
    text = open(deck_path, encoding="utf-8", errors="replace").read()
    text, nb = re.subn(r'(ct[xyz]\s+=\s+")([\d.]+)"', lambda m: m.group(1) + str(float(m.group(2))*30.0) + '"', text)
    text, n1 = re.subn(r'"[^"]*Motor_PSM_dual\.fmu"'.replace("PSM", "PMSM"), '"' + os.path.join(run, os.path.basename(CHAMP)).replace("\\", "/") + '"', text)
    text, n2 = re.subn(r'(id\s+=\s+"-535050562"\s*\n\s*string\s+=\s+")ModelExchange(")', r"\g<1>CoSimulation\g<2>", text)
    text, n3 = re.subn(r'"[^"]*custom_event_tipout_10\.adf"', '"' + (run + "/static_hold.adf").replace("\\", "/") + '"', text)
    text, n = apply_springs(text, front_k=fk, front_preload=front, rear_k=rk, rear_preload=rear)
    open(deck_path, "w", encoding="utf-8").write(text)
    print(f"{tag}: damping x30 ({nb}), fmu x{n1}, mode x{n2}, adf x{n3}, preloads front x{n['front']} rear x{n['rear']}", flush=True)
    if n["front"] != 2 or n["rear"] != 2 or n1 != 1 or n3 != 1:
        raise SystemExit("PATCH COUNTS WRONG")
    env = os.environ.copy()
    dirs = []
    for m in re.finditer(r'"([A-Za-z]:[^"]+?\.dll)"', text, re.IGNORECASE):
        d = os.path.dirname(m.group(1).replace("/", os.sep))
        if os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
    t0 = time.time()
    rc = subprocess.run([BAT, DECK], cwd=run, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=1800).returncode
    print(f"{tag}: solver exit {rc} in {(time.time()-t0)/60:.1f} min", flush=True)
    t, data, ids = plt_reader.read_plt(os.path.join(run, "AVLlit_tipin_50pct.plt"))[:3]
    i = np.searchsorted(t, min(1.2, t[-1]))
    fl_z, fr_z, rl_z, rr_z = data[i, 0, 2], data[i, 2, 2], data[i, 4, 2], data[i, 6, 2]
    fb, rb = np.abs(data[i, 48, :3]).max(), np.abs(data[i, 56, :3]).max()
    fgap, rgap = data[i, 16, 2], data[i, 32, 2]
    print(f"{tag}: t={t[i]:.2f} wheel-centre z vs design [mm] FL {fl_z:.1f} FR {fr_z:.1f} RL {rl_z:.1f} RR {rr_z:.1f} | "
          f"jounce bumper force front {fb:.0f} N rear {rb:.0f} N | bumper disp front {fgap:.1f} rear {rgap:.1f} | "
          f"tyre Fz FL {data[i,123,2]:.0f} RL {data[i,137,2]:.0f} | pitch {data[i,79,0]:.2f} deg", flush=True)
    print("RESULT", _j.dumps(dict(front=front, rear=rear, front_k=fk, rear_k=rk, fl=float(fl_z), rl=float(rl_z), fb=float(fb), rb=float(rb), fgap=float(fgap), rgap=float(rgap), run=run)), flush=True)


if __name__ == "__main__":
    main()
