"""PRXAnalyzer — slope/ratio diagnostics for non-reciprocal Hertzian runs.

Phase C split: extracted from toolClass.py:439-773 (originally lines 423-773).
"""
import json as _json
import datetime as _dt
import string as _string
import subprocess as _subprocess
from pathlib import Path as _Path

# Plotting / numerics — hoisted to module level so the 9 plot methods
# don't each re-import. matplotlib.use("Agg") MUST come before pyplot
# import; this file is pure-Python with no GUI need.
import numpy as _np
import h5py as _h5py
import matplotlib as _mpl
_mpl.use("Agg")
import matplotlib.pyplot as _plt


class PRXAnalyzer:
    """Slope sweep, paper-comparison verdict, and full per-run analysis.

    Paper anchors (PRX 2015 Ivlev, Hertzian non-reciprocal NVE):
      - asymptotic slope    α = 2/3
      - asymptotic ratio    τ_∞ = T_A / T_B = 3.1
      - tolerance for PASS  10 %
    """

    PAPER_SLOPE = 2.0 / 3.0
    PAPER_RATIO = 3.1
    TOLERANCE = 0.10
    DEFAULT_TMIN_GRID = (5, 50, 500, 2000, 5000, 10000, 20000, 30000)

    @staticmethod
    def rolling_slopes(time, TA, TB, tmin_grid=None):
        """Log-spaced rolling slope sweep. Drops windows with < 50 frames.

        Returns a list of dicts: tmin, n, slope_A, slope_B, mean_TA,
        mean_TB, ratio. Latest entry is the most asymptotic estimate.
        """
        import numpy as _np
        rows = []
        grid = tmin_grid or PRXAnalyzer.DEFAULT_TMIN_GRID
        for tmin in grid:
            mask = time > tmin
            if mask.sum() < 50:
                continue
            log_t = _np.log10(time[mask])
            sA = _np.polyfit(log_t, _np.log10(_np.maximum(TA[mask], 1e-30)), 1)[0]
            sB = _np.polyfit(log_t, _np.log10(_np.maximum(TB[mask], 1e-30)), 1)[0]
            rA = TA[mask].mean()
            rB = TB[mask].mean()
            rows.append({
                "tmin": tmin,
                "n": int(mask.sum()),
                "slope_A": float(sA),
                "slope_B": float(sB),
                "mean_TA": float(rA),
                "mean_TB": float(rB),
                "ratio": float(rA / max(rB, 1e-30)),
            })
        return rows

    @staticmethod
    def paper_verdict(slope_A, slope_B, ratio, ke_growing,
                      tol=None):
        """Compute PASS/FAIL × 4 metrics with relative errors."""
        tol = tol if tol is not None else PRXAnalyzer.TOLERANCE
        err_A = abs(slope_A - PRXAnalyzer.PAPER_SLOPE) / PRXAnalyzer.PAPER_SLOPE
        err_B = abs(slope_B - PRXAnalyzer.PAPER_SLOPE) / PRXAnalyzer.PAPER_SLOPE
        err_R = abs(ratio - PRXAnalyzer.PAPER_RATIO) / PRXAnalyzer.PAPER_RATIO
        return {
            "slope_A_err": err_A,
            "slope_B_err": err_B,
            "ratio_err": err_R,
            "slope_A_verdict": "PASS" if err_A < tol else "FAIL",
            "slope_B_verdict": "PASS" if err_B < tol else "FAIL",
            "ratio_verdict": "PASS" if err_R < tol else "FAIL",
            "ke_verdict": "PASS" if ke_growing else "FAIL",
            "all_pass": (err_A < tol and err_B < tol and err_R < tol
                         and ke_growing),
        }

    @staticmethod
    def write_slope_csv(rows, path):
        path = _Path(path)
        with path.open("w", encoding="utf-8") as f:
            f.write("tmin_tau,n_frames,slope_A,slope_B,"
                    "mean_T_A,mean_T_B,ratio\n")
            for r in rows:
                f.write(f"{r['tmin']},{r['n']},{r['slope_A']:.5f},"
                        f"{r['slope_B']:.5f},{r['mean_TA']:.4e},"
                        f"{r['mean_TB']:.4e},{r['ratio']:.4f}\n")

    @staticmethod
    def slope_table_text(rows):
        head = (f"  {'tmin (τ)':>9}  {'frames':>7}  {'slope_A':>9}  "
                f"{'slope_B':>9}  {'<T_A>':>9}  {'<T_B>':>9}  "
                f"{'ratio':>8}\n")
        body = ""
        for r in rows:
            body += (f"  {r['tmin']:>9}  {r['n']:>7}  {r['slope_A']:>9.4f}  "
                     f"{r['slope_B']:>9.4f}  {r['mean_TA']:>9.4f}  "
                     f"{r['mean_TB']:>9.4f}  {r['ratio']:>8.4f}\n")
        return head + body

    @staticmethod
    def load_run(run_dir):
        """Read manifest.json + the largest HDF5 in run_dir.

        Returns a dict with: manifest, time, TA, TB, attrs, n_atoms, h5_path.
        """
        run_dir = _Path(run_dir)
        h5s = sorted(run_dir.glob("*.h5"), key=lambda p: p.stat().st_size)
        if not h5s:
            raise FileNotFoundError(f"no HDF5 in {run_dir}")
        h5_path = h5s[-1]

        manifest_path = run_dir / "manifest.json"
        manifest = (_json.loads(manifest_path.read_text(encoding="utf-8"))
                    if manifest_path.exists() else {})

        with _h5py.File(h5_path, "r") as f:
            species = f["species"][:]
            T_all = f["T"][:]
            time = f["time"][:]
            attrs = dict(f.attrs)
            try:
                box = f["box"][:]
            except Exception:
                box = None

        mA = species == 1
        mB = species == 2
        return {
            "run_dir": run_dir,
            "h5_path": h5_path,
            "manifest": manifest,
            "attrs": attrs,
            "species": species,
            "time": time,
            "TA": T_all[:, mA].mean(axis=1),
            "TB": T_all[:, mB].mean(axis=1),
            "T_all": T_all,
            "box": box,
            "n_atoms_A": int(mA.sum()),
            "n_atoms_B": int(mB.sum()),
        }

    @staticmethod
    def full_analysis(run_dir, template_path=None):
        """End-to-end per-run analysis. Writes:
          - slope_sweep.csv
          - slope_overlay.png
          - report.md (rendered from template)

        Returns the dict of fields used to render the template.
        """
        run_dir = _Path(run_dir)
        rec = PRXAnalyzer.load_run(run_dir)
        time = rec["time"]; TA = rec["TA"]; TB = rec["TB"]
        attrs = rec["attrs"]; manifest = rec["manifest"]

        rows = PRXAnalyzer.rolling_slopes(time, TA, TB)
        PRXAnalyzer.write_slope_csv(rows, run_dir / "slope_sweep.csv")

        # Plots
        tag = manifest.get("tag", run_dir.name)
        title = (f"{tag}: T₀={manifest.get('T0_star', '?')}, "
                 f"φ={manifest.get('phi_target', '?')}, "
                 f"{time[-1]:.0f} τ")
        plot_path = run_dir / "slope_overlay.png"
        PRXPlotter.slope_overlay(time, TA, TB, rows, plot_path, title=title)

        # NEW: T_A/T_B vs t (paper Fig 2 inset analog)
        ratio_plot = run_dir / "ratio_vs_time.png"
        try:
            PRXPlotter.ratio_vs_time(rec, ratio_plot,
                                       title=f"{tag}: T_A/T_B vs t")
        except Exception as _e:
            print(f"[PRXAnalyzer] ratio plot skipped: {_e}")
            ratio_plot = None

        # NEW: velocity distribution at t=700 τ (or t_end/3 if shorter).
        # Paper Fig 1 lower panel reference.
        vd_plot = run_dir / "velocity_dist.png"
        try:
            t_target = 700.0 if time[-1] >= 700 else time[-1] / 3.0
            PRXPlotter.velocity_distribution(rec, t_target, vd_plot)
        except Exception as _e:
            print(f"[PRXAnalyzer] velocity dist plot skipped: {_e}")
            vd_plot = None

        # Verdict
        if rows:
            last = rows[-1]
            slope_A, slope_B, ratio = (last["slope_A"], last["slope_B"],
                                         last["ratio"])
        else:
            slope_A = slope_B = ratio = float("nan")
        ke_growing = TA[-1] > TA[0]
        v = PRXAnalyzer.paper_verdict(slope_A, slope_B, ratio, ke_growing)

        # Headline phrase
        if v["all_pass"]:
            headline = ("**ALL PASS** — paper Fig 1 quantitatively reproduced "
                        "for this (φ, T₀).")
        elif v["slope_A_verdict"] == "PASS" and ke_growing:
            headline = ("**slope PASS, ratio NEAR** — primary asymptote "
                        "captured; T_A/T_B finite-time deviation expected.")
        elif v["slope_A_err"] < 0.20:
            headline = ("**near-asymptote** — slope_A within 20 % of 2/3; "
                        "longer run probably needed to PASS hard rule.")
        else:
            headline = ("**transient** — slope_A still well below 2/3; "
                        "either run longer or accept this point as paper "
                        "boundary case.")

        # Wall + step rate
        wall = manifest.get("wall_seconds")
        if wall:
            wall_str = f"{int(wall // 3600)}:{int((wall % 3600)//60):02d}:{int(wall%60):02d}"
            steps = manifest.get("steps", attrs.get("write_stride", 1) * len(time))
            step_rate = steps / wall if wall else float("nan")
        else:
            wall_str = "n/a"
            step_rate = float("nan")

        phi = manifest.get("phi_target", float("nan"))
        T0 = manifest.get("T0_star", float("nan"))

        # Resource estimate (re-computed from manifest for record)
        try:
            est = ResourceEstimator.estimate_run({
                "N": manifest.get("N_A", 0),
                "steps": manifest.get("steps", 0),
                "stride": manifest.get("write_stride", 1),
                "chunk_size": manifest.get("chunk_size", 200),
            })
            est_block = (f"VRAM ~{est['vram_gb']:.2f} GB | "
                         f"RAM peak ~{est['ram_peak_gb']:.2f} GB | "
                         f"wall ~{est['wall_hours']:.2f} hr | "
                         f"disk ~{est['disk_gb']:.2f} GB")
        except Exception:
            est_block = "n/a"

        # Render template
        if template_path is None:
            template_path = (_Path(__file__).resolve().parent
                             / "docs" / "PRX_run_report_template.md")
        template_text = _Path(template_path).read_text(encoding="utf-8")

        fields = {
            "TAG": tag,
            "H5_RELPATH": rec["h5_path"].name,
            "H5_SIZE_GB": f"{rec['h5_path'].stat().st_size / 1e9:.2f}",
            "RUN_DIR": str(run_dir),
            "SLOPE_A": _fmt(slope_A),
            "SLOPE_B": _fmt(slope_B),
            "SLOPE_A_ABSERR": _fmt(slope_A - PRXAnalyzer.PAPER_SLOPE),
            "SLOPE_B_ABSERR": _fmt(slope_B - PRXAnalyzer.PAPER_SLOPE),
            "SLOPE_A_RELERR": f"{v['slope_A_err'] * 100:.2f} %",
            "SLOPE_B_RELERR": f"{v['slope_B_err'] * 100:.2f} %",
            "SLOPE_A_VERDICT": v["slope_A_verdict"],
            "SLOPE_B_VERDICT": v["slope_B_verdict"],
            "RATIO": _fmt(ratio),
            "RATIO_ABSERR": _fmt(ratio - PRXAnalyzer.PAPER_RATIO),
            "RATIO_RELERR": f"{v['ratio_err'] * 100:.2f} %",
            "RATIO_VERDICT": v["ratio_verdict"],
            "KE_TREND": "growing" if ke_growing else "shrinking",
            "KE_VERDICT": v["ke_verdict"],
            "HEADLINE": headline,
            "PHI": _fmt(phi, 3),
            "T0": _fmt(T0, 3),
            "NU": _fmt(manifest.get("nu", 0.0), 4),
            "DT": _fmt(attrs.get("physics_dt", attrs.get("dt", float("nan"))), 4),
            "N_TOTAL": _fmt(attrs.get("num_atoms", float("nan")), 0),
            "N_PER_SPECIES": _fmt(rec["n_atoms_A"], 0),
            "STEPS": _fmt(manifest.get("steps", float("nan")), 0),
            "STRIDE": _fmt(attrs.get("write_stride", float("nan")), 0),
            "CHUNK_SIZE": _fmt(manifest.get("chunk_size", 200), 0),
            "T_END": _fmt(time[-1], 1),
            "N_FRAMES": _fmt(len(time), 0),
            "DT_PER_FRAME": _fmt(attrs.get("dt", float("nan")), 4),
            "WALL": wall_str,
            "STEP_RATE": (f"{step_rate:.0f}" if step_rate == step_rate
                          else "n/a"),
            "GIT_SHA": manifest.get("git_sha", "n/a"),
            "T_START": manifest.get("started_at", "n/a"),
            "T_END_ISO": manifest.get(
                "finished_at",
                _dt.datetime.now().isoformat(timespec="seconds")),
            "TA_INIT": _fmt(TA[0]),
            "TA_FINAL": _fmt(TA[-1]),
            "TA_GROWTH": _fmt(TA[-1] / max(TA[0], 1e-30), 2),
            "TB_INIT": _fmt(TB[0]),
            "TB_FINAL": _fmt(TB[-1]),
            "TB_GROWTH": _fmt(TB[-1] / max(TB[0], 1e-30), 2),
            "RATIO_INIT": _fmt(TA[0] / max(TB[0], 1e-30)),
            "RATIO_FINAL": _fmt(TA[-1] / max(TB[-1], 1e-30)),
            "SLOPE_TABLE": PRXAnalyzer.slope_table_text(rows),
            "LATEST_TMIN": (_fmt(rows[-1]["tmin"], 0) if rows else "n/a"),
            "LATEST_NFRAMES": (_fmt(rows[-1]["n"], 0) if rows else "n/a"),
            "PRIOR_COMPARISON": PriorRunsDB.markdown_table(
                phi, T0, exclude_tag=tag),
            "FILE_LISTING": _file_listing(run_dir),
            "NOTES": manifest.get("notes", "_none_"),
            "RESOURCE_ESTIMATE": est_block,
        }
        rendered = _string.Template(template_text).safe_substitute(fields)
        report_path = run_dir / "report.md"
        report_path.write_text(rendered, encoding="utf-8")

        print(f"[PRXAnalyzer] {tag}: slope_A={slope_A:.4f} "
              f"({v['slope_A_err']*100:.2f}% err) — {v['slope_A_verdict']}; "
              f"ratio={ratio:.3f} ({v['ratio_err']*100:.2f}% err) — "
              f"{v['ratio_verdict']}")
        return fields


def _fmt(x, nd=4):
    """Number formatter with int/float/None handling. Used by templates."""
    import numpy as _np
    if isinstance(x, (int, _np.integer)):
        return str(int(x))
    if x is None:
        return "n/a"
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return str(x)


def _file_listing(run_dir):
    """Compact human-readable directory listing for embedding in reports."""
    run_dir = _Path(run_dir)
    lines = []
    for p in sorted(run_dir.iterdir()):
        try:
            sz = p.stat().st_size
            if sz > 1e9:
                ssz = f"{sz/1e9:.2f} GB"
            elif sz > 1e6:
                ssz = f"{sz/1e6:.2f} MB"
            elif sz > 1e3:
                ssz = f"{sz/1e3:.2f} KB"
            else:
                ssz = f"{sz} B"
            lines.append(f"  {ssz:>10}  {p.name}")
        except Exception:
            lines.append(f"  ?           {p.name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Extension diagnostics (PRX-specific): pair correlation + per-species KE +
# total-momentum drift. Originally `scripts/extension_analysis.py`; merged
# here so any caller can invoke `PRXAnalyzer.extension_diagnostics(run_dir)`.
# ---------------------------------------------------------------------------

def _pair_correlation_2d(positions, species, box_size,
                          r_max: float = 6.0, n_bins: int = 100):
    """Per-species pair correlation g_AA(r), g_BB(r), g_AB(r) in 2D PBC.

    Args:
        positions: (n, 3) array; only x,y used (z dropped).
        species:   (n,) array; species id 1 == A, 2 == B.
        box_size:  [Lx, Ly] length-2 sequence.
        r_max:     histogram extent (reduced units).
        n_bins:    histogram bin count.

    Returns dict with keys 'r', 'g_AA', 'g_BB', 'g_AB'.
    """
    pos2d = positions[:, :2]
    Lx, Ly = box_size[0], box_size[1]
    mA = species == 1
    mB = species == 2
    pA = pos2d[mA]; pB = pos2d[mB]
    nA = len(pA); nB = len(pB)
    area = Lx * Ly

    bin_edges = _np.linspace(0, r_max, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    bin_areas = _np.pi * (bin_edges[1:] ** 2 - bin_edges[:-1] ** 2)

    def _mic(P, Q):
        d = P[:, None, :] - Q[None, :, :]
        d[..., 0] -= Lx * _np.round(d[..., 0] / Lx)
        d[..., 1] -= Ly * _np.round(d[..., 1] / Ly)
        return _np.linalg.norm(d, axis=-1)

    def _gxx(P, n_self):
        if n_self <= 1:
            return _np.zeros(n_bins)
        d = _mic(P, P)
        d = d[_np.triu_indices(n_self, k=1)]
        h, _ = _np.histogram(d, bins=bin_edges)
        rho = n_self / area
        norm = rho * bin_areas * (n_self / 2.0)
        return h / _np.maximum(norm, 1)

    g_AA = _gxx(pA, nA)
    g_BB = _gxx(pB, nB)
    if nA > 0 and nB > 0:
        d_AB = _mic(pA, pB).ravel()
        h_AB, _ = _np.histogram(d_AB, bins=bin_edges)
        rho_B = nB / area
        norm_AB = rho_B * bin_areas * nA
        g_AB = h_AB / _np.maximum(norm_AB, 1)
    else:
        g_AB = _np.zeros(n_bins)
    return {"r": bin_centers, "g_AA": g_AA, "g_BB": g_BB, "g_AB": g_AB}


def _attach_extension(cls):
    @staticmethod
    def pair_correlation(positions, species, box_size,
                          r_max: float = 6.0, n_bins: int = 100):
        """See _pair_correlation_2d."""
        return _pair_correlation_2d(positions, species, box_size, r_max, n_bins)

    @staticmethod
    def extension_diagnostics(run_dir):
        """Read a single run dir and emit pair-correlation + per-species KE +
        momentum-drift figures to that dir.

        Side effects:
            <run_dir>/extension_pair_correlation.png
            <run_dir>/extension_energy_momentum.png
            <run_dir>/extension_summary.json
        Returns the summary dict.
        """
        import json as _json
        run_dir = _Path(run_dir)
        h5_paths = sorted(run_dir.glob("*.h5"), key=lambda p: p.stat().st_size)
        if not h5_paths:
            raise FileNotFoundError(f"no *.h5 under {run_dir}")
        h5_path = h5_paths[-1]
        manifest = _json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        tag = manifest.get("tag", run_dir.name)

        with _h5py.File(h5_path, "r") as f:
            species = f["species"][:]
            time = f["time"][:]
            T_all = f["T"][:]
            box = f["box"][:]
            n_frames = T_all.shape[0]
            idx_early = int(n_frames * 0.05)
            idx_mid   = int(n_frames * 0.50)
            idx_late  = int(n_frames * 0.95)
            gr_results = {}
            for label, idx in [("early", idx_early), ("mid", idx_mid), ("late", idx_late)]:
                pos = f["pos"][idx]
                gr_results[label] = _pair_correlation_2d(
                    pos, species, [box[0, 0], box[1, 1]], r_max=6.0, n_bins=100)
                gr_results[label]["t"] = float(time[idx])

            diag_indices = _np.linspace(0, n_frames - 1, 50, dtype=int)
            ke_A = _np.zeros(len(diag_indices))
            ke_B = _np.zeros(len(diag_indices))
            px = _np.zeros(len(diag_indices))
            py = _np.zeros(len(diag_indices))
            mA = species == 1; mB = species == 2
            for i, idx in enumerate(diag_indices):
                v = f["vel"][idx]
                ke_A[i] = 0.5 * (v[mA, :2] ** 2).sum()
                ke_B[i] = 0.5 * (v[mB, :2] ** 2).sum()
                px[i] = v[:, 0].sum()
                py[i] = v[:, 1].sum()
            diag_t = time[diag_indices]

        # Figure 1: g(r) at three time snapshots
        fig, axs = _plt.subplots(1, 3, figsize=(15, 4.8))
        for ax, label in zip(axs, ["early", "mid", "late"]):
            gr = gr_results[label]
            ax.plot(gr["r"], gr["g_AA"], "C0-", label="g_AA(r)", lw=1.5)
            ax.plot(gr["r"], gr["g_BB"], "C1-", label="g_BB(r)", lw=1.5)
            ax.plot(gr["r"], gr["g_AB"], "C2-", label="g_AB(r)", lw=1.5)
            ax.axhline(1.0, color="gray", ls=":", alpha=0.5)
            ax.axvline(1.0, color="black", ls=":", alpha=0.3, label="r₀")
            ax.set_xlabel("r"); ax.set_ylabel("g(r)")
            ax.set_title(f"{label}-time, t={gr['t']:.0f} τ")
            ax.legend(fontsize=8, loc="upper right")
            ax.grid(alpha=0.3); ax.set_xlim(0, 6)
        _plt.tight_layout()
        pair_png = run_dir / "extension_pair_correlation.png"
        _plt.savefig(pair_png, dpi=140); _plt.close(fig)

        # Figure 2: per-species KE + total momentum drift
        fig, axs = _plt.subplots(1, 2, figsize=(13, 4.8))
        mask = diag_t > 1
        axs[0].loglog(diag_t[mask], ke_A[mask], "C0-o", lw=1.0, markersize=3,
                       label="KE_A")
        axs[0].loglog(diag_t[mask], ke_B[mask], "C1-s", lw=1.0, markersize=3,
                       label="KE_B")
        axs[0].loglog(diag_t[mask], (ke_A + ke_B)[mask], "k--", alpha=0.6,
                       label="total KE")
        axs[0].set_xlabel("t (τ)"); axs[0].set_ylabel("KE")
        axs[0].set_title(f"{tag}: per-species kinetic energy")
        axs[0].legend(fontsize=9); axs[0].grid(which="both", alpha=0.3)
        p_total = _np.sqrt(px ** 2 + py ** 2)
        axs[1].plot(diag_t, px, "C0-", lw=1.0, label="P_x")
        axs[1].plot(diag_t, py, "C1-", lw=1.0, label="P_y")
        axs[1].plot(diag_t, p_total, "k--", lw=1.0, alpha=0.6, label="|P| total")
        axs[1].axhline(0, color="gray", ls=":", alpha=0.5)
        axs[1].set_xlabel("t (τ)"); axs[1].set_ylabel("P (per particle)")
        axs[1].set_title(f"{tag}: total momentum drift (non-reciprocal)")
        axs[1].legend(fontsize=9); axs[1].grid(alpha=0.3)
        _plt.tight_layout()
        energy_png = run_dir / "extension_energy_momentum.png"
        _plt.savefig(energy_png, dpi=140); _plt.close(fig)

        def _peak(g):
            return float(g[_np.argmax(g[5:50]) + 5])
        summary = {
            "tag": tag,
            "g_late_AA_first_peak": _peak(gr_results["late"]["g_AA"]),
            "g_late_BB_first_peak": _peak(gr_results["late"]["g_BB"]),
            "g_late_AB_first_peak": _peak(gr_results["late"]["g_AB"]),
            "ke_A_initial": float(ke_A[0]), "ke_A_final": float(ke_A[-1]),
            "ke_B_initial": float(ke_B[0]), "ke_B_final": float(ke_B[-1]),
            "ke_ratio_late": float(ke_A[-1] / max(ke_B[-1], 1e-30)),
            "P_total_max": float(_np.max(p_total)),
            "P_total_final": float(p_total[-1]),
        }
        summary_path = run_dir / "extension_summary.json"
        summary_path.write_text(_json.dumps(summary, indent=2))
        return summary

    cls.pair_correlation = pair_correlation
    cls.extension_diagnostics = extension_diagnostics
    return cls


PRXAnalyzer = _attach_extension(PRXAnalyzer)



