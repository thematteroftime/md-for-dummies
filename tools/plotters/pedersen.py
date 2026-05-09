"""PedersenPlotter — KA-LJ partial RDF + MSD per-run figures.

Reads `<run_dir>/rdf.npz` + `<run_dir>/msd.npz` (written by PedersenAnalyzer)
and produces:
  • `<run_dir>/fig1_rdf.png`  — three-panel g_AA, g_AB, g_BB
  • `<run_dir>/fig2_msd.png`  — MSD_A and MSD_B vs t

Cross-run figures (called by PedersenAggregator):
  • `fig_rdf_overlay(records, out_path)`
  • `fig_msd_overlay(records, out_path)`
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


class PedersenPlotter:
    @staticmethod
    def render(run_dir, **params):
        run_dir = Path(run_dir)
        manifest = {}
        if (run_dir / "manifest.json").exists():
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        tag = manifest.get("tag", run_dir.name)
        T0 = manifest.get("T0", "?")
        rho = manifest.get("rho", "?")

        # --- fig1: partial RDFs ---
        rdf_path = run_dir / "rdf.npz"
        if not rdf_path.exists():
            print(f"[PedersenPlotter] {run_dir} has no rdf.npz — skipping fig1")
        else:
            d = np.load(rdf_path)
            r = d["r"]; g_AA = d["g_AA"]; g_AB = d["g_AB"]; g_BB = d["g_BB"]
            n_avg = int(d.get("n_frames_avg", 0))

            fig, axs = plt.subplots(1, 3, figsize=(15, 4.5), sharey=True)
            for ax, g, label, color, expected in (
                (axs[0], g_AA, "g_AA(r)", "C0", 1.122),
                (axs[1], g_AB, "g_AB(r)", "C1", 0.898),
                (axs[2], g_BB, "g_BB(r)", "C2", 0.988),
            ):
                ax.plot(r, g, color=color, lw=1.5, label=label)
                ax.axhline(1.0, color="k", ls=":", alpha=0.4, label="g=1")
                ax.axvline(expected, color="r", ls="--", alpha=0.5,
                            label=f"σ·2^{{1/6}}={expected:.3f}")
                ax.set_xlim(0, min(r[-1], 4.0))
                ax.set_xlabel("r (σ_AA)")
                ax.set_title(label)
                ax.grid(alpha=0.3)
                ax.legend(fontsize=8, loc="upper right")
            axs[0].set_ylabel("g(r)")
            fig.suptitle(f"{tag}: KA-LJ partial RDFs (T0={T0}, ρ={rho}, "
                          f"averaged over {n_avg} frames)", fontsize=11)
            plt.tight_layout()
            out_path = run_dir / "fig1_rdf.png"
            plt.savefig(out_path, dpi=140, bbox_inches="tight")
            plt.close(fig)
            print(f"[PedersenPlotter] wrote {out_path}")

        # --- fig2: MSD ---
        msd_path = run_dir / "msd.npz"
        if not msd_path.exists():
            print(f"[PedersenPlotter] {run_dir} has no msd.npz — skipping fig2")
            return
        d = np.load(msd_path)
        t = d["t"]; msd_A = d["msd_A"]; msd_B = d["msd_B"]

        fig, ax = plt.subplots(1, 1, figsize=(8, 5))
        ax.plot(t, msd_A, "C0-", lw=1.5, label=f"MSD_A (final={msd_A[-1]:.3f})")
        ax.plot(t, msd_B, "C3-", lw=1.5, label=f"MSD_B (final={msd_B[-1]:.3f})")
        ax.set_xlabel("t (τ)")
        ax.set_ylabel("MSD (σ_AA²)")
        ax.set_title(f"{tag}: KA-LJ MSD (T0={T0}, ρ={rho}) — qualitative; "
                     f"engine drag-only Langevin")
        ax.legend(loc="best")
        ax.grid(alpha=0.3)
        plt.tight_layout()
        out_path = run_dir / "fig2_msd.png"
        plt.savefig(out_path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        print(f"[PedersenPlotter] wrote {out_path}")

    # ----- cross-run figures (used by PedersenAggregator) -----

    @staticmethod
    def fig_rdf_overlay(records, out_path, **params):
        """Overlay g_AA from each run on a single panel, color-coded by T0."""
        fig, ax = plt.subplots(1, 3, figsize=(15, 4.5), sharey=True)
        cmap = plt.get_cmap("viridis")
        T0s = sorted({float(rec["manifest"].get("T0", 0)) for rec in records})
        T0_to_color = {t: cmap(i / max(1, len(T0s) - 1)) for i, t in enumerate(T0s)}

        for rec in records:
            rd = rec["run_dir"]
            rdf_path = Path(rd) / "rdf.npz"
            if not rdf_path.exists():
                continue
            d = np.load(rdf_path)
            r = d["r"]
            T0 = float(rec["manifest"].get("T0", 0))
            color = T0_to_color[T0]
            tag = rec["manifest"].get("tag", "?")
            for axi, key, label in (
                (ax[0], "g_AA", "g_AA"),
                (ax[1], "g_AB", "g_AB"),
                (ax[2], "g_BB", "g_BB"),
            ):
                axi.plot(r, d[key], color=color, lw=1.2,
                          label=f"{tag} T0={T0}")
        for axi, label, expected in (
            (ax[0], "g_AA(r)", 1.122),
            (ax[1], "g_AB(r)", 0.898),
            (ax[2], "g_BB(r)", 0.988),
        ):
            axi.axvline(expected, color="r", ls="--", alpha=0.5)
            axi.axhline(1.0, color="k", ls=":", alpha=0.4)
            axi.set_xlabel("r (σ_AA)")
            axi.set_xlim(0, 4.0)
            axi.set_title(label)
            axi.grid(alpha=0.3)
            axi.legend(fontsize=7, loc="upper right")
        ax[0].set_ylabel("g(r)")
        plt.tight_layout()
        plt.savefig(out_path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        print(f"[PedersenPlotter] wrote {out_path}")

    @staticmethod
    def fig_msd_overlay(records, out_path, **params):
        """Overlay MSD_A from each run, color-coded by T0."""
        fig, ax = plt.subplots(1, 1, figsize=(9, 5))
        cmap = plt.get_cmap("plasma")
        T0s = sorted({float(rec["manifest"].get("T0", 0)) for rec in records})
        T0_to_color = {t: cmap(i / max(1, len(T0s) - 1)) for i, t in enumerate(T0s)}
        for rec in records:
            rd = rec["run_dir"]
            msd_path = Path(rd) / "msd.npz"
            if not msd_path.exists():
                continue
            d = np.load(msd_path)
            T0 = float(rec["manifest"].get("T0", 0))
            color = T0_to_color[T0]
            tag = rec["manifest"].get("tag", "?")
            ax.plot(d["t"], d["msd_A"], color=color, lw=1.5,
                     label=f"{tag} T0={T0}")
        ax.set_xlabel("t (τ)")
        ax.set_ylabel("MSD_A (σ_AA²)")
        ax.set_title("KA-LJ MSD_A overlay (paper Fig.3 isodiffusional analog; qualitative)")
        ax.legend(loc="best", fontsize=9)
        ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        print(f"[PedersenPlotter] wrote {out_path}")
