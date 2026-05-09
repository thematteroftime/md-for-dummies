"""PedersenAggregator — KA-LJ cross-run report builder.

Aggregates per-run results (RDF peaks, MSD) across all runs in a campaign,
writes the master `docs/pedersen_kalj_campaign_report.md`, and renders
overlay figures via PedersenPlotter.fig_rdf_overlay / fig_msd_overlay.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterable

from tools.analyzers.pedersen import PedersenAnalyzer
from tools.plotters.pedersen import PedersenPlotter


class PedersenAggregator:
    @staticmethod
    def aggregate(run_dirs: Iterable, output: str, plots, title: str = "",
                  **params):
        run_dirs = [Path(p) for p in run_dirs]
        records = []
        for rd in run_dirs:
            try:
                records.append(PedersenAnalyzer.load_run(rd))
            except Exception as e:
                print(f"[PedersenAggregator] could not load {rd}: {e}")

        out_md = Path(output)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        img_dir = Path("docs/images")
        img_dir.mkdir(parents=True, exist_ok=True)

        # 1. Render named cross-run figures
        fig_paths = []
        plot_methods = {
            "rdf_overlay": PedersenPlotter.fig_rdf_overlay,
            "msd_overlay": PedersenPlotter.fig_msd_overlay,
        }
        for short in plots or []:
            method = plot_methods.get(short)
            if method is None:
                print(f"[PedersenAggregator] unknown plot '{short}' — skipping")
                continue
            out_png = img_dir / f"pedersen_kalj_{short}.png"
            method(records, out_png, **params)
            fig_paths.append(out_png)

        # 2. Master markdown
        lines = [f"# {title or 'Pedersen KA-LJ campaign report'}", ""]
        lines.append(f"Runs: {len(records)}")
        lines.append("")
        lines.append("| tag | T0 | rho | N | r_peak_AA | r_peak_AB | r_peak_BB | "
                      "ordering r_AB<r_AA | MSD_A_final |")
        lines.append("| --- | -- | --- | - | --------- | --------- | --------- | "
                      "------------------- | ----------- |")
        for rec in records:
            man = rec["manifest"]
            tag = man.get("tag", "?")
            T0 = man.get("T0", "?")
            rho = man.get("rho", "?")
            N = man.get("N", "?")
            # Re-run analysis quickly for the table (cheap; cached from h5).
            try:
                fields = PedersenAnalyzer.full_analysis(rec["run_dir"])
                r_AA = f"{fields['r_peak_AA']:.3f}"
                r_AB = f"{fields['r_peak_AB']:.3f}"
                r_BB = f"{fields['r_peak_BB']:.3f}"
                ordering = "PASS" if fields["ordering_pass"] else "FAIL"
                msd = f"{fields['msd_A_final']:.3f}"
            except Exception as e:
                r_AA = r_AB = r_BB = ordering = msd = f"err({e})"
            lines.append(f"| {tag} | {T0} | {rho} | {N} | {r_AA} | {r_AB} | {r_BB} | "
                          f"{ordering} | {msd} |")
        lines.append("")
        for png in fig_paths:
            try:
                rel = png.relative_to(out_md.parent)
            except ValueError:
                rel = png
            lines.append(f"![{png.stem}]({rel})")
            lines.append("")

        out_md.write_text("\n".join(lines), encoding="utf-8")
        print(f"[PedersenAggregator] wrote {out_md}")
