# Candidate Papers for `paper-to-experiment` End-to-End Test

Selection criteria recap (HARD):
- APS journal (PRL/PRX preferred, PRE acceptable)
- Open access PDF actually downloadable
- Classical, pair-potential MD-friendly model (not DFT/AIMD/ML/coarse-grain)
- Reproducible at N <= 5000, steps <= 1e6
- At least one quantitative observable (curve / phase boundary / scalar)
- Different physics from already-reproduced papers (Hertzian non-reciprocal, anisotropic Yukawa, 2D Yukawa OCP)

All four PDFs below have been verified as real PDFs (`%PDF-` magic header) and are stored in this folder.

---

## Candidate 1 (RECOMMENDED): Bernard & Krauth, PRL 2011

**Citation.** E. P. Bernard and W. Krauth, "Two-Step Melting in Two Dimensions: First-Order Liquid-Hexatic Transition", Phys. Rev. Lett. **107**, 155704 (2011). DOI: 10.1103/PhysRevLett.107.155704. arXiv: 1102.4094.

**Summary.** Demonstrates that the 2D hard-disk system melts in two steps: a first-order liquid-hexatic transition followed by a continuous hexatic-solid (KTHNY) transition. Resolves a 50-year debate using event-chain Monte Carlo on systems up to N ~ 1e6, but the qualitative two-step signature appears at far smaller N.

**Force / system.** ndim=2; pair potential is the **hard-disk** interaction (V=infinity for r<sigma, 0 otherwise). Reduced units rho* = N sigma^2 / V. Hard-core can be implemented in MD via WCA-truncated soft repulsion (e.g. r^-50 or steeply truncated LJ) without changing the qualitative phase structure — this is exactly what Engel 2013 confirms (see candidate 2).

**Key observable.** Equation of state P(rho*) showing a Mayer-Wood pressure loop at the liquid-hexatic transition (Fig. 1, 2), and the orientational correlation function g6(r) decaying algebraically in the hexatic phase, exponentially in the liquid (Fig. 3). Bond-orientational order parameter psi6 distribution.

**Smallest reproducible scale.** N ~ 1024-4096 disks, ~1e5-1e6 sweeps. The Mayer-Wood loop is visible at N=1024 already in Engel et al. follow-up work; pushed to N >= 16384 to clearly see the first-order character. For our skill test, N=2048-4096 is plenty to see g6 decay change behavior across the transition.

**Why this paper.** Forces our skill to exercise:
1. **New force class** — `HardDiskRepulsive` (or steeply repulsive WCA n=50 IPL) — not yet in framework.
2. **New analyzer** — bond-orientational order psi6 and g6(r), plus a Mayer-Wood-style P(rho) sweep. Distinct from existing RDF/MSD analyzers.
3. **New initial config** — 2D triangular lattice with controlled rho*.
4. **2D mode** — exercises the zeroZ-trick for 2D inside the 3-vec storage.

**PDF status.** Downloaded from arXiv. File: `papers/bernard_prl2011.pdf` (905 KB, %PDF- verified).

---

## Candidate 2: Engel, Anderson, Glotzer, Isobe, Bernard, Krauth, PRE 2013

**Citation.** M. Engel, J. A. Anderson, S. C. Glotzer, M. Isobe, E. P. Bernard, W. Krauth, "Hard-disk equation of state: First-order liquid-hexatic transition in two dimensions with three simulation methods", Phys. Rev. E **87**, 042134 (2013). DOI: 10.1103/PhysRevE.87.042134. arXiv: 1211.1645.

**Summary.** Cross-validates the Bernard-Krauth result using three independent methods: event-chain MC, event-driven MD, and massively parallel MC. Provides the cleanest equation-of-state data and consistency tables for the hexatic-liquid coexistence densities.

**Force / system.** ndim=2; hard disks. Identical model to candidate 1 but with explicit MD reference data — a direct target for our MD framework.

**Key observable.** P(phi) equation of state in packing-fraction phi (Fig. 1, 2); coexistence densities phi_l = 0.700, phi_h = 0.716 (Table I); g6(r) algebraic vs exponential (Fig. 7).

**Smallest reproducible scale.** They go large (N up to 1024^2) but N=128^2=16384 already shows the loop; we can target N=4096 with shorter runs and still see qualitative pressure plateau + g6 difference between two state points across the transition.

**Why this paper.** Same physics as candidate 1 but its inclusion of MD numbers (event-driven MD column) gives us a direct quantitative benchmark in MD units. Slightly heavier than candidate 1 — keep as backup if Bernard-Krauth's pure-MC framing turns out to confuse the skill.

**PDF status.** Downloaded from arXiv. File: `papers/engel_pre2013.pdf` (1.5 MB, %PDF- verified).

---

## Candidate 3: Pedersen, Schroder, Dyre, PRL 2018

**Citation.** U. R. Pedersen, T. B. Schroder, J. C. Dyre, "Phase Diagram of Kob-Andersen-Type Binary Lennard-Jones Mixtures", Phys. Rev. Lett. **120**, 165501 (2018). DOI: 10.1103/PhysRevLett.120.165501. arXiv: 1803.08956.

**Summary.** Computes the equilibrium thermodynamic phase diagram of the canonical Kob-Andersen 80:20 binary LJ glass-former, showing that the standard KA mixture is metastable: it crystallizes by phase-separating the A-particles into an FCC crystal at T_m = 1.028 (rho=1.2). Resolves a long-standing question about whether KA is a "true" glass-former or just slow-crystallizing.

**Force / system.** ndim=3; **binary Lennard-Jones** with KA parameters: epsilon_AA=1, epsilon_AB=1.5, epsilon_BB=0.5, sigma_AA=1, sigma_AB=0.8, sigma_BB=0.88; r_cut=2.5 sigma. Standard cubic box, NVT/NPT.

**Key observable.** Coexistence pressure-temperature line for the A-FCC + binary-fluid coexistence (Fig. 2); melting temperature T_m(rho) curve (Fig. 3); also the chemical-potential-difference observable Delta-mu used in Frenkel-Ladd-style integration.

**Smallest reproducible scale.** They use N in the few-thousand range for direct coexistence runs (N=2916 reported). 1e5-1e6 steps is sufficient to equilibrate at moderate supercooling. N=4000 fits comfortably in our limits.

**Why this paper.** Forces:
1. **New force class** — `BinaryLennardJones` (per-pair epsilon/sigma matrix) — extends the existing single-species LJ in the framework.
2. **New analyzer** — partial RDFs g_AA, g_AB, g_BB and per-species MSD; phase-detection via crystal order parameter Q6 on A-particles only.
3. **Multi-species manifest** — exercises type tagging in the I/O layer.
4. Tests 3D crystallization at modest scale.

**PDF status.** Downloaded from arXiv. File: `papers/pedersen_prl2018.pdf` (2.5 MB, %PDF- verified).

---

## Candidate 4: Prestipino, Saija, Giaquinta, PRE 2005

**Citation.** S. Prestipino, F. Saija, P. V. Giaquinta, "Phase diagram of the Gaussian-core model", Phys. Rev. E **71**, 050102(R) (2005). DOI: 10.1103/PhysRevE.71.050102. arXiv: cond-mat/0506012.

**Summary.** Maps the 3D phase diagram of point particles interacting via a purely repulsive Gaussian pair potential V(r)=epsilon exp(-(r/sigma)^2), revealing the celebrated **fluid-BCC-FCC-BCC-fluid reentrant** sequence on isothermal compression at T just above the triple point.

**Force / system.** ndim=3; **Gaussian-core** pair potential (no hard core, finite at r=0 — exotic feature). NVT MC, easily portable to NVT MD with our framework.

**Key observable.** Phase boundaries in (rho, T) plane (Fig. 1); per-particle free energies of the BCC and FCC competing crystals (Fig. 2); reentrant melting curve.

**Smallest reproducible scale.** Original work uses ~1000-4000 particles for free-energy runs; the **reentrant melting curve** is qualitatively visible at N~2000 over a few-1e5 sweeps. Target N=2000-4000 for our skill test.

**Why this paper.** Forces:
1. **New force class** — `GaussianCore` — penetrable bounded potential (genuinely new physics, very different from LJ/Yukawa/Hertzian).
2. **New analyzer** — phase identifier via Steinhardt Q4/Q6 to discriminate BCC vs FCC.
3. Tests robustness of integrator to a finite-energy core (no divergence at r=0).
4. Caveat: original is MC, but in MD with NVT thermostat and the same potential the BCC region is reproducible — Lang/Kahl have MD references in subsequent literature.

**PDF status.** Downloaded from arXiv. File: `papers/prestipino_pre2005.pdf` (251 KB, %PDF- verified).

---

## Recommendation

**Pick candidate 1 (Bernard-Krauth PRL 2011)** as the primary test target.

Rationale: it is the textbook 2D-melting paper of the past 15 years; it cleanly hits a different physics regime than what the framework already covers (no Yukawa, no Hertzian, no anisotropy); the qualitative result (two-step melting with first-order liquid-hexatic) is *robust at N=2048-4096*; and the required new pieces — a hard-disk-like repulsion (or n=50 IPL surrogate), a psi6/g6 analyzer, and a 2D triangular initialization — are exactly the kind of "add a new force class + new analyzer" extensions the skill is meant to cover. Candidate 2 (Engel 2013) is its natural fallback since it provides explicit MD benchmark numbers for the same model, and candidate 3 (Pedersen 2018) is the strongest 3D / multi-species fallback if you'd rather exercise the binary-species code path instead.
