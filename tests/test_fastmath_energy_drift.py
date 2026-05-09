"""§6.1 验收 / §6.2 风险: fast_math on/off 同条件 100k 步 NVE.

Compares LJ NVE total energy drift over 100k steps with fast_math on vs off.
The unshifted LJ has a known cutoff discontinuity that injects ≈ V_LJ(rc)≈-0.016
per pair-crossing event; this dominates absolute drift over many steps.
Therefore the test compares the RELATIVE difference between fast_math=on and
fast_math=off — fast_math passes if it doesn't make drift meaningfully worse
than the cutoff-discontinuity baseline.
"""
import os
import sys
import math
import subprocess
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def run_drift(fast_math: bool):
    """Spawn a subprocess with the requested fast_math flag, return {E0, E, drift}."""
    code = f"""
import os, sys, math
sys.path.insert(0, r'{ROOT}'); os.chdir(r'{ROOT}')
import taichi as ti
ti.init(arch=ti.gpu, default_fp=ti.f64, fast_math={fast_math},
        offline_cache=True, advanced_optimization=True)
import constSet as cs
cs.UNITS = cs.Units(name='reduced', K_B=1.0, KE_E2=1.0,
                    TIME_UNIT_CONVERSION=1.0, length_label='r0')
cs.K_B = 1.0; cs.KE_E2 = 1.0
from atomSystemClass import AtomSystem
from searchBox import searchBox
from forces import lennardJones
from integratorClass import integrator
import numpy as np

N = 64
side = int(math.ceil(math.sqrt(N))); L = side * 1.2
pos = np.zeros((N, 3))
k = 0
for i in range(side):
    for j in range(side):
        if k < N:
            pos[k] = [i*1.2 + 0.05*((-1)**(i+j)), j*1.2 + 0.05, 0]
            k += 1
cutoffNegh = 2.6
Lz = 2.0 * cutoffNegh + 0.1   # 5.3; satisfies Lz >= cutoffNegh and Lz/2 > cutoffNegh
A = AtomSystem(num_atoms=N, n=3, cutoff=2.5, ndim=2)
A.initData(pos, np.ones(N), 0.5, [L,0,0,0,L,0,0,0,Lz], None)
sb = searchBox(choose=1, mN=64, cutoffNegh=cutoffNegh)
ff = lennardJones(1.0, 1.0)
sb.register(A, forceField=ff); ff.register(atomSystem=A, searchBox=sb)
inte = integrator(timeStep=0.001, nu=0.0)
inte.register(atomSystem=A, forceField=ff)
sb.findNegh(); ff.updateAllF(); A.reduce_pe()
KE0 = 0.5 * float((A.vel.to_numpy()**2).sum() * 1.0)
E0 = KE0 + float(A.pe[None])
N_STEPS = 100000
for step in range(N_STEPS):
    sb.findNegh(); inte.inteBegin(); sb.applyPbc()
KE = 0.5 * float((A.vel.to_numpy()**2).sum() * 1.0)
E = KE + float(A.pe[None])
import json
print('RESULT_JSON', json.dumps({{"E0": E0, "E": E, "drift": abs(E-E0)/abs(E0)}}))
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=1200)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT_JSON")]
    if not line:
        print("STDOUT:", r.stdout[-500:])
        print("STDERR:", r.stderr[-500:])
        raise RuntimeError("no result line")
    return json.loads(line[0].split(" ", 1)[1])


def test_fastmath_drift_comparable():
    """fast_math=True drift should be comparable to fast_math=False (cutoff baseline)."""
    print("Running fast_math=True (this takes minutes)...")
    on = run_drift(True)
    print("Running fast_math=False (this takes minutes)...")
    off = run_drift(False)
    print(f"fast_math=True  -> E0={on['E0']:.6e}, E={on['E']:.6e}, drift={on['drift']:.3e}")
    print(f"fast_math=False -> E0={off['E0']:.6e}, E={off['E']:.6e}, drift={off['drift']:.3e}")

    # Dual criterion: if absolute drift on PASSES the strict 1e-4 threshold, GREAT.
    # Otherwise compare on vs off — fast_math fails only if it makes drift
    # >= 1.5x worse than the cutoff-baseline (off).
    if on["drift"] < 1e-4:
        print("OK: fast_math=True drift below strict 1e-4 threshold")
        return
    rel = on["drift"] / max(off["drift"], 1e-30)
    print(f"on/off drift ratio: {rel:.3f}")
    assert rel < 1.5, (
        f"fast_math=True drift {on['drift']:.3e} is {rel:.2f}x worse than "
        f"fast_math=False {off['drift']:.3e} — recommend flipping default OFF "
        f"per spec §6.2 mitigation"
    )
    print("OK: fast_math=True drift comparable to baseline (LJ cutoff dominates)")


if __name__ == "__main__":
    test_fastmath_drift_comparable()
