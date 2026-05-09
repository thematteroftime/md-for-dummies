"""ResourceEstimator + PriorRunsDB — preflight cost estimates and prior-run lookup.

Phase C split: extracted from toolClass.py:1132-1290.
"""
import json as _json
import datetime as _dt
import string as _string
import subprocess as _subprocess
from pathlib import Path as _Path
import numpy as _np
import h5py as _h5py

class ResourceEstimator:
    """Predict GPU memory, peak RAM, wall time, and disk usage for a planned
    PRX run before launching it.

    All inputs in reduced units, ndim=3 (we always store 3D vectors).
    Estimates are conservative; observed values typically come in 10-30 %
    below predicted.
    """

    NDIM = 3
    BYTES_PER_FLOAT = 8

    @staticmethod
    def estimate_run(config):
        """Given a config dict (N, steps, stride, chunk_size), return
        a dict of estimates."""
        N_per = int(config.get("N", 10000))
        N_total = N_per * 2
        steps = int(config.get("steps", 1_000_000))
        stride = int(config.get("stride", 1))
        chunk_size = int(config.get("chunk_size", 200))

        # VRAM (Taichi fields):
        #   - pos, vel: each (N, 3) double  =  N * 24 bytes
        #   - data_pos, data_vel buffers: each (chunk_size, N, 3) doubles
        #   - data_T: (chunk_size, N) double
        #   - cell list ~ 2 * N * 4 bytes
        per_step = N_total * ResourceEstimator.NDIM * ResourceEstimator.BYTES_PER_FLOAT
        chunk_buf = (2 * chunk_size * N_total * ResourceEstimator.NDIM
                     + chunk_size * N_total) * ResourceEstimator.BYTES_PER_FLOAT
        vram_bytes = 4 * per_step + chunk_buf + 256 * 1024 * 1024  # 256 MB Taichi runtime
        vram_gb = vram_bytes / 1e9

        # Peak RAM (Python + queue):
        #   queue maxsize=8 chunks, each chunk holds copy of (pos, vel, T)
        #   plus writer-thread working copy ~ 1 chunk
        per_chunk_bytes = (2 * chunk_size * N_total * ResourceEstimator.NDIM
                           + chunk_size * N_total) * ResourceEstimator.BYTES_PER_FLOAT
        ram_peak_bytes = 8 * per_chunk_bytes + 1.5e9  # +1.5 GB Python overhead
        ram_peak_gb = ram_peak_bytes / 1e9

        # Wall: empirically ~300 step/s for N=20000 cell-list, slowing 30%
        # over a long run. Linear scaling in N.
        # For N_total=20000: 300 step/s -> 3.33ms/step -> 30000τ would take
        # ~11 hr at our throughput. Use that as anchor.
        BASE_STEP_RATE = 300.0  # step/s at N_total=20000
        BASE_N = 20000
        scale = (BASE_N / max(N_total, 1))
        # Slowdown factor of 1.4 for high-T phases of a long run
        SLOWDOWN = 1.4
        step_rate_eff = BASE_STEP_RATE * scale / SLOWDOWN
        wall_seconds = steps / step_rate_eff
        wall_hours = wall_seconds / 3600.0

        # Disk: per-frame stored bytes (after LZF ~3x):
        #   pos (N*3*8) + vel (N*3*8) + T (N*8) per frame
        #   plus 8 bytes for time
        n_frames = max(1, steps // stride)
        per_frame_raw = (2 * N_total * ResourceEstimator.NDIM + N_total) * ResourceEstimator.BYTES_PER_FLOAT
        raw_bytes = n_frames * per_frame_raw
        # LZF compression ratio ~2.8x (empirical from R6 + E1v3)
        disk_bytes = raw_bytes / 2.8 + 5e6  # +5 MB metadata
        disk_gb = disk_bytes / 1e9

        return {
            "N_total": N_total,
            "steps": steps,
            "stride": stride,
            "chunk_size": chunk_size,
            "n_frames": n_frames,
            "vram_gb": vram_gb,
            "ram_peak_gb": ram_peak_gb,
            "wall_seconds": wall_seconds,
            "wall_hours": wall_hours,
            "disk_gb": disk_gb,
            "step_rate_eff": step_rate_eff,
            "tau_end": steps * float(config.get("dt", 0.004)),
        }

    @staticmethod
    def _force_specific_header(config):
        """Return the parenthesized parameter summary for the preflight banner,
        dispatched by `force_type`. Falls back to the PRX (φ, T₀) shape if
        the force_type is unknown or unset."""
        force_type = config.get("force_type", "hertzian_nonreciprocal")
        try:
            from forces import FORCE_REGISTRY
            ForceCls = FORCE_REGISTRY.get(force_type)
            fields = getattr(ForceCls, "PREFLIGHT_FIELDS", ()) if ForceCls else ()
        except Exception:
            fields = ()
        if not fields:
            phi = config.get("phi", config.get("phi_target", "?"))
            T0 = config.get("T0", config.get("T0_star", "?"))
            return f"φ={phi}, T₀={T0}"
        # Only show fields the user actually populated; drop steps/N which the
        # main banner prints anyway.
        skip = {"steps", "N"}
        parts = [f"{k}={config[k]}" for k in fields if k in config and k not in skip]
        return ", ".join(parts) if parts else f"force_type={force_type}"

    @staticmethod
    def print_preflight(config, est=None):
        """Pretty-print preflight estimate. Returns the est dict."""
        if est is None:
            est = ResourceEstimator.estimate_run(config)
        tag = config.get("tag", "?")
        header_params = ResourceEstimator._force_specific_header(config)
        print()
        print(f"  ╔═══════════════════════════════════════════════════════════╗")
        print(f"  ║   PREFLIGHT — {tag}  ({header_params})                       ")
        print(f"  ╠═══════════════════════════════════════════════════════════╣")
        print(f"  ║ steps          = {est['steps']:>12,}                          ")
        print(f"  ║ N_total        = {est['N_total']:>12,}                          ")
        print(f"  ║ stride         = {est['stride']:>12}                          ")
        print(f"  ║ chunk_size     = {est['chunk_size']:>12}                          ")
        print(f"  ║ τ end (sim)    = {est['tau_end']:>12.0f}                          ")
        print(f"  ║ frames written = {est['n_frames']:>12,}                          ")
        print(f"  ╠═══════════════════════════════════════════════════════════╣")
        print(f"  ║ VRAM est.      = {est['vram_gb']:>10.2f} GB                       ")
        print(f"  ║ RAM peak est.  = {est['ram_peak_gb']:>10.2f} GB                       ")
        print(f"  ║ Wall est.      = {est['wall_hours']:>10.2f} hr  (@ {est['step_rate_eff']:.0f} step/s eff)")
        print(f"  ║ Disk (HDF5)    = {est['disk_gb']:>10.2f} GB  (LZF ~2.8x)            ")
        print(f"  ╚═══════════════════════════════════════════════════════════╝")
        print()
        return est


class PriorRunsDB:
    """Static catalog of completed PRX runs for cross-reference.

    Each entry: (phi, T0, tag, tau_end, slope_A_late, T_ratio, comment).
    Update this when a new long-time run lands so future reports
    automatically pick it up.
    """

    PRIORS = [
        # phi, T0,   tag,    tau_end, slope_A, ratio,  status
        (0.1,  1.0, "R6a",    3000,  0.18,    2.57,   "transient"),
        (0.3,  1.0, "R3",     3000,  0.21,    2.84,   "transient"),
        (0.3,  1.0, "R4-N40k",1500,  0.19,    2.71,   "transient"),
        (0.5,  1.0, "R6b",    3000,  0.26,    2.86,   "transient"),
        (0.7,  1.0, "R5b",    3000,  0.39,    2.94,   "near-asymptote"),
        (0.9,  1.0, "R6c",    3000,  0.40,    2.92,   "near-asymptote"),
        (0.3, 10.0, "R6d",    3000,  0.16,    1.49,   "transient"),
        (0.3,  0.3, "R6e",    3000,  0.51,    2.91,   "transient"),
        (0.3,  0.3, "E1v3",  20000,  0.6617,  2.86,   "asymptote (PASS)"),
    ]

    @staticmethod
    def find(phi, T0, exclude_tag=None, tol=1e-6):
        """Return prior runs matching (phi, T0)."""
        out = []
        for row in PriorRunsDB.PRIORS:
            if (abs(row[0] - phi) < tol and abs(row[1] - T0) < tol
                    and row[2] != exclude_tag):
                out.append({
                    "phi": row[0], "T0": row[1], "tag": row[2],
                    "tau_end": row[3], "slope_A": row[4],
                    "ratio": row[5], "status": row[6],
                })
        return out

    @staticmethod
    def markdown_table(phi, T0, exclude_tag=None):
        rows = PriorRunsDB.find(phi, T0, exclude_tag=exclude_tag)
        if not rows:
            return ("_no prior run at this (φ, T₀) in the database — "
                    "this is a fresh parameter point._")
        lines = [
            "| Run | τ run | slope_A late | T_A/T_B | Status |",
            "| --- | ----- | ------------ | ------- | ------ |",
        ]
        for r in rows:
            lines.append(
                f"| {r['tag']} | {r['tau_end']} | {r['slope_A']:.3f} | "
                f"{r['ratio']:.2f} | {r['status']} |")
        return "\n".join(lines)



