"""PedersenAnalyzer — KA-LJ binary mixture per-run analysis.

Reads `<run_dir>/manifest.json` + the trajectory `*.h5`, computes:
  • Partial radial distribution functions g_AA(r), g_AB(r), g_BB(r)
    averaged over the last third of the trajectory.
  • Mean-square displacement (MSD) of A and B atoms vs t (since frame 0).
  • First-peak positions r_AA*, r_AB*, r_BB* — used as PASS/FAIL gates.

Writes:
  • `<run_dir>/rdf.npz`   keys: r, g_AA, g_AB, g_BB, n_frames_avg
  • `<run_dir>/msd.npz`   keys: t, msd_A, msd_B
  • `<run_dir>/report.md` markdown summary

Returns dict with verdict + metrics (contract: see ARCHITECTURE.md §3.3 and
docs/specs/.../pedersen-kalj-design.md §1.5).
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import h5py


class PedersenAnalyzer:
    """KA-LJ binary mixture analyzer (Pedersen PRL 2018)."""

    # ------- Pass-criteria thresholds (from design doc §6) -------
    R_AA_PASS = (1.00, 1.20)
    R_AA_NEAR = (0.95, 1.30)
    R_AB_PASS = (0.78, 0.95)
    R_AB_NEAR = (0.70, 1.00)
    R_BB_PASS = (0.88, 1.05)
    R_BB_NEAR = (0.80, 1.10)
    MSD_LIQUID_PASS = 0.5     # σ_AA² at t_end if T > T_m (liquid mobile)
    MSD_LIQUID_NEAR = 0.1

    @staticmethod
    def load_run(run_dir):
        run_dir = Path(run_dir)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

        h5s = sorted(run_dir.glob("*.h5"), key=lambda p: p.stat().st_size)
        if not h5s:
            raise FileNotFoundError(f"no HDF5 in {run_dir}")
        h5_path = h5s[-1]

        with h5py.File(h5_path, "r") as f:
            time = f["time"][:]
            pos = f["pos"][:]
            species = f["species"][:]
            attrs = dict(f.attrs)
            try:
                box = f["box"][:]
            except Exception:
                box = None

        return {
            "run_dir": run_dir,
            "h5_path": h5_path,
            "manifest": manifest,
            "attrs": attrs,
            "time": time,
            "pos": pos,
            "species": species,
            "box": box,
        }

    @staticmethod
    def _partial_rdf(positions, species, box_lengths, group_i, group_j,
                     r_max=None, n_bins=200):
        """Compute partial RDF g_pq(r) averaged over multiple frames.

        positions: (n_frames, N, 3)
        species:   (N,) int (1=A, 2=B)
        box_lengths: (3,)
        group_i, group_j: 1 or 2 (the two species to correlate)

        Returns (r_centers, g) numpy arrays of length n_bins.
        """
        n_frames, N, _ = positions.shape
        Lx, Ly, Lz = box_lengths
        L = np.array([Lx, Ly, Lz])
        V = float(Lx * Ly * Lz)

        idx_i = np.where(species == group_i)[0]
        idx_j = np.where(species == group_j)[0]
        N_i = len(idx_i)
        N_j = len(idx_j)
        same_species = (group_i == group_j)

        if r_max is None:
            r_max = 0.5 * float(min(L))    # half-box (PBC limit)
        edges = np.linspace(0.0, r_max, n_bins + 1)
        centers = 0.5 * (edges[:-1] + edges[1:])
        bin_w = edges[1] - edges[0]

        hist_total = np.zeros(n_bins, dtype=np.float64)

        for frame_idx in range(n_frames):
            pos = positions[frame_idx]
            ri = pos[idx_i]                 # (N_i, 3)
            rj = pos[idx_j]                 # (N_j, 3)
            # All-pairs displacement; for AA we'll exclude self-pairs.
            # Memory: O(N_i · N_j · 3) — 800 · 800 · 24 = 15 MB per frame. OK.
            dr = ri[:, None, :] - rj[None, :, :]    # (N_i, N_j, 3)
            # Minimum image
            dr -= np.round(dr / L) * L
            dist = np.linalg.norm(dr, axis=-1)       # (N_i, N_j)
            # Mask: exclude r=0 (self-pairs in AA case)
            mask = dist > 1e-9
            d_valid = dist[mask]
            d_in_range = d_valid[d_valid < r_max]
            counts, _ = np.histogram(d_in_range, bins=edges)
            hist_total += counts

        # Normalize: g(r) = (V / N_pair) · count / (4π r² dr · n_frames)
        # N_pair = N_i · (N_i - 1) for same species, N_i · N_j for different.
        n_pairs = N_i * (N_i - 1) if same_species else N_i * N_j
        if n_pairs == 0:
            return centers, np.zeros_like(centers)
        # Volume of each spherical shell
        shell_vol = 4.0 * np.pi * centers ** 2 * bin_w
        # Number density of "j" species (target species the pair points to)
        # Actually for proper normalization: g(r) = count(i,j in dr) / (n_pairs · ρ_avg · shell_vol / V)
        # which simplifies to: g(r) = V · count / (n_pairs · shell_vol · n_frames)
        with np.errstate(divide="ignore", invalid="ignore"):
            g = (V * hist_total) / (n_pairs * shell_vol * n_frames)
        g = np.nan_to_num(g, nan=0.0, posinf=0.0, neginf=0.0)
        return centers, g

    @staticmethod
    def _msd(positions, species, group, dt_per_frame, box_lengths):
        """Mean-square displacement for the given species, with PBC unwrap.

        positions: (n_frames, N, 3)
        Returns (t, msd) arrays.
        """
        n_frames = positions.shape[0]
        if n_frames < 2:
            return np.array([0.0]), np.array([0.0])
        idx = np.where(species == group)[0]
        if len(idx) == 0:
            return np.zeros(n_frames), np.zeros(n_frames)
        L = np.array(box_lengths)

        # Naive unwrapping: track frame-to-frame delta and remove PBC jumps.
        pos_sub = positions[:, idx, :].copy()
        unwrapped = np.zeros_like(pos_sub)
        unwrapped[0] = pos_sub[0]
        for k in range(1, n_frames):
            delta = pos_sub[k] - pos_sub[k - 1]
            delta -= np.round(delta / L) * L
            unwrapped[k] = unwrapped[k - 1] + delta

        ref = unwrapped[0]
        sq_disp = np.sum((unwrapped - ref) ** 2, axis=-1)   # (n_frames, N_sub)
        msd = sq_disp.mean(axis=1)
        t = np.arange(n_frames) * dt_per_frame
        return t, msd

    @staticmethod
    def _first_peak(r, g):
        """Return r at the FIRST significant peak in g(r), ignoring r<0.5 noise.

        The previous (argmax) version picked the tallest peak, which for low-N
        species (e.g. N_B=200 → 200·199 BB pairs) can be a statistical fluke
        in the second or third shell. We instead:
          1. Smooth g with a 5-bin moving average.
          2. Apply scipy.signal.find_peaks with a modest height threshold.
          3. Return the smallest r among the first 3 peaks if they exceed g≥1.0
             (the LJ first peak in a fluid is always > 1).
        """
        from scipy.signal import find_peaks
        mask = r > 0.5
        if not mask.any():
            return float("nan")
        rr = r[mask]
        gg = g[mask]
        if len(gg) >= 5:
            kernel = np.ones(5) / 5.0
            gs = np.convolve(gg, kernel, mode="same")
        else:
            gs = gg
        # Find peaks above g=1.0 (true LJ first-coordination shell).
        peaks, _ = find_peaks(gs, height=1.0)
        if len(peaks) == 0:
            # Fall back to argmax of the smoothed RDF if no qualifying peak.
            return float(rr[int(np.argmax(gs))])
        # Return the first peak (smallest r).
        return float(rr[int(peaks[0])])

    @staticmethod
    def _classify_peak(r_peak, pass_band, near_band):
        if pass_band[0] <= r_peak <= pass_band[1]:
            return "PASS"
        if near_band[0] <= r_peak <= near_band[1]:
            return "NEAR"
        return "FAIL"

    @staticmethod
    def full_analysis(run_dir, **params):
        """Required Phase-3.4 hook.

        params (all optional):
          n_bins (int, default 200) — RDF histogram bins
          tail_fraction (float, default 0.33) — fraction of trajectory used
                                                for RDF averaging (last X)
          frame_stride (int, default 5) — subsample frames for cheaper RDF
        """
        run_dir = Path(run_dir)
        rec = PedersenAnalyzer.load_run(run_dir)
        manifest = rec["manifest"]
        time = rec["time"]
        pos = rec["pos"]
        species = rec["species"]

        # Box lengths from manifest (more reliable than h5 attrs for our adapter).
        Lx = manifest.get("Lx") or float(rec["box"][0, 0]) if rec["box"] is not None else None
        Ly = manifest.get("Ly") or float(rec["box"][1, 1]) if rec["box"] is not None else None
        Lz = manifest.get("Lz") or float(rec["box"][2, 2]) if rec["box"] is not None else None
        if Lx is None or Ly is None or Lz is None:
            raise RuntimeError(f"could not determine box from {run_dir}")
        box_lengths = (float(Lx), float(Ly), float(Lz))

        n_bins = int(params.get("n_bins", 200))
        tail_fraction = float(params.get("tail_fraction", 0.33))
        frame_stride = int(params.get("frame_stride", 5))

        n_frames = pos.shape[0]
        n_tail = max(2, int(n_frames * tail_fraction))
        tail_pos = pos[-n_tail::frame_stride]    # subsampled tail
        n_used = tail_pos.shape[0]

        # Three partial RDFs
        r, g_AA = PedersenAnalyzer._partial_rdf(
            tail_pos, species, box_lengths, 1, 1, n_bins=n_bins)
        _, g_AB = PedersenAnalyzer._partial_rdf(
            tail_pos, species, box_lengths, 1, 2, n_bins=n_bins)
        _, g_BB = PedersenAnalyzer._partial_rdf(
            tail_pos, species, box_lengths, 2, 2, n_bins=n_bins)

        np.savez(
            run_dir / "rdf.npz",
            r=r, g_AA=g_AA, g_AB=g_AB, g_BB=g_BB,
            n_frames_avg=n_used, box_lengths=np.array(box_lengths),
        )

        # MSD over full trajectory (every frame)
        dt_per_frame = float(rec["attrs"].get("dt", manifest.get("dt", 1.0))
                              * manifest.get("write_stride", 1))
        # Actually attrs["dt"] = physics_dt × stride per systemClass writer; that
        # IS the per-frame dt. So use it directly.
        dt_per_frame = float(rec["attrs"].get("dt", 1.0))
        t_msd, msd_A = PedersenAnalyzer._msd(pos, species, 1, dt_per_frame, box_lengths)
        _, msd_B = PedersenAnalyzer._msd(pos, species, 2, dt_per_frame, box_lengths)

        np.savez(
            run_dir / "msd.npz",
            t=t_msd, msd_A=msd_A, msd_B=msd_B,
        )

        # First-peak positions
        r_peak_AA = PedersenAnalyzer._first_peak(r, g_AA)
        r_peak_AB = PedersenAnalyzer._first_peak(r, g_AB)
        r_peak_BB = PedersenAnalyzer._first_peak(r, g_BB)

        verd_AA = PedersenAnalyzer._classify_peak(
            r_peak_AA, PedersenAnalyzer.R_AA_PASS, PedersenAnalyzer.R_AA_NEAR)
        verd_AB = PedersenAnalyzer._classify_peak(
            r_peak_AB, PedersenAnalyzer.R_AB_PASS, PedersenAnalyzer.R_AB_NEAR)
        verd_BB = PedersenAnalyzer._classify_peak(
            r_peak_BB, PedersenAnalyzer.R_BB_PASS, PedersenAnalyzer.R_BB_NEAR)

        # Ordering check (O4): r_AB < r_AA
        ordering_pass = r_peak_AB < r_peak_AA

        # Aggregate verdict
        peak_passes = [verd_AA == "PASS", verd_AB == "PASS", verd_BB == "PASS"]
        if all(peak_passes) and ordering_pass:
            verdict = "PASS"
        elif ordering_pass and sum(peak_passes) >= 2:
            verdict = "NEAR"
        else:
            verdict = "FAIL"

        msd_A_final = float(msd_A[-1]) if len(msd_A) > 0 else float("nan")
        msd_B_final = float(msd_B[-1]) if len(msd_B) > 0 else float("nan")

        T0 = manifest.get("T0", float("nan"))
        rho = manifest.get("rho", float("nan"))
        N_A = manifest.get("N_A", "?")
        N_B = manifest.get("N_B", "?")
        tag = manifest.get("tag", run_dir.name)

        # ---------- report.md ----------
        report = []
        report.append(f"# Pedersen KA-LJ run report — {tag}")
        report.append("")
        report.append(f"**verdict**: **{verdict}**")
        report.append("")
        report.append(f"- T0 = {T0}, ρ = {rho}, N = {N_A + N_B if isinstance(N_A, int) and isinstance(N_B, int) else '?'} "
                       f"(A={N_A}, B={N_B})")
        report.append(f"- box = {box_lengths[0]:.3f} × {box_lengths[1]:.3f} × {box_lengths[2]:.3f}")
        report.append(f"- frames total = {n_frames}, frames used for RDF = {n_used} "
                       f"(last {tail_fraction*100:.0f}% subsampled by {frame_stride})")
        report.append(f"- per-frame dt = {dt_per_frame:.4f} τ; t_end = {time[-1] if len(time) else 0:.2f} τ")
        report.append("")
        report.append("## Partial RDF first-peak positions")
        report.append("")
        report.append("| pair | r_peak (σ_AA) | expected (paper) | verdict |")
        report.append("|------|---------------|------------------|---------|")
        report.append(f"| g_AA | {r_peak_AA:.4f} | ~1.0–1.2 (LJ near σ·2^{{1/6}}≈1.122) | {verd_AA} |")
        report.append(f"| g_AB | {r_peak_AB:.4f} | ~0.78–0.95 (σ_AB·2^{{1/6}}≈0.898)   | {verd_AB} |")
        report.append(f"| g_BB | {r_peak_BB:.4f} | ~0.88–1.05 (σ_BB·2^{{1/6}}≈0.988)   | {verd_BB} |")
        report.append("")
        report.append(f"- ordering check r_AB < r_AA → **{'PASS' if ordering_pass else 'FAIL'}** "
                       f"(r_AB - r_AA = {r_peak_AB - r_peak_AA:+.4f} σ_AA)")
        report.append("")
        report.append("## Mean-square displacement (qualitative; engine has drag-only Langevin)")
        report.append("")
        report.append(f"- MSD_A(t_end) = {msd_A_final:.4f} σ_AA²")
        report.append(f"- MSD_B(t_end) = {msd_B_final:.4f} σ_AA²")
        report.append("")
        if T0 >= 1.2 and msd_A_final >= PedersenAnalyzer.MSD_LIQUID_PASS:
            report.append("- T0 is above the paper T_m≈1.028 — MSD finite and ≥ 0.5 indicates liquid mobility ✔")
        elif T0 >= 1.2 and msd_A_final >= PedersenAnalyzer.MSD_LIQUID_NEAR:
            report.append("- T0 above T_m but MSD below threshold — short trajectory or engine cooling artifact")
        elif T0 < 0.9:
            report.append("- T0 below paper T_m — supercooled / glassy regime; small MSD is expected and / or engine artifact")
        else:
            report.append("- T0 near T_m — MSD interpretation depends on equilibration window")
        report.append("")
        report.append("## Files written")
        report.append("")
        report.append("- `rdf.npz` — r, g_AA, g_AB, g_BB (for plotter)")
        report.append("- `msd.npz` — t, msd_A, msd_B (for plotter)")
        report.append("- `report.md` — this file")
        report.append("")
        report.append("## Engine limitations (as designed)")
        report.append("")
        report.append("- BAOAB Langevin without Wiener noise → MSD plateaus at low T are an engine artifact, not physics.")
        report.append("- No NPT → paper's coexistence-line method (Fig.1) is not reproducible. We use NVT-Langevin at fixed ρ; observables are qualitative.")

        report_path = run_dir / "report.md"
        report_path.write_text("\n".join(report), encoding="utf-8")
        print(f"[PedersenAnalyzer] {tag}: verdict={verdict} "
              f"r_peak_AA={r_peak_AA:.3f} r_peak_AB={r_peak_AB:.3f} r_peak_BB={r_peak_BB:.3f}")

        return {
            "verdict": verdict,
            "r_peak_AA": r_peak_AA,
            "r_peak_AB": r_peak_AB,
            "r_peak_BB": r_peak_BB,
            "verdict_AA": verd_AA,
            "verdict_AB": verd_AB,
            "verdict_BB": verd_BB,
            "ordering_pass": ordering_pass,
            "msd_A_final": msd_A_final,
            "msd_B_final": msd_B_final,
            "T0": T0,
            "rho": rho,
            "params": params,
        }
