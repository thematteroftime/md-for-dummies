"""Shared primitives for paper-specific analyzers.

Helpers here should be paper-agnostic — anything with paper context belongs
in `tools/analyzers/<paper>.py`.

When in doubt, write the helper in your paper's analyzer first and only
promote here once a second analyzer needs it.
"""
from __future__ import annotations
from pathlib import Path
import json
from typing import Optional

import numpy as np


def first_peak(
    r: np.ndarray,
    g: np.ndarray,
    g_floor: float = 1.0,
    smooth: int = 0,
) -> Optional[tuple]:
    """Return (r_peak, g_peak) of the smallest-r local maximum with g >= g_floor.

    For partial RDFs of binary mixtures with a sparse minority species
    (e.g. KA 80:20 with N_B=200), `np.argmax(g)` can return a spurious
    second-shell statistical fluctuation. Walking outward from r=0 and
    taking the first peak above 1.0 is robust.

    Parameters
    ----------
    r : array of bin centers (monotonically increasing).
    g : array of g(r) values (same length as r).
    g_floor : minimum height for a peak to count. Default 1.0 (above the
              uncorrelated baseline). Use 0.5 for sparse statistics or
              < 1 normalisation conventions.
    smooth : optional uniform-window smoothing length (0 = no smoothing).
             Use 3-5 for very noisy g(r) with few bin counts.

    Returns
    -------
    (r_peak, g_peak) tuple of floats, or None if no qualifying peak found.
    """
    g_use = g
    if smooth and smooth > 1:
        kernel = np.ones(int(smooth)) / float(int(smooth))
        g_use = np.convolve(g, kernel, mode="same")

    # Walk outward; a peak is g[i] > g[i-1] AND g[i] >= g[i+1] AND g[i] >= g_floor.
    n = len(g_use)
    for i in range(1, n - 1):
        if g_use[i] >= g_floor and g_use[i] > g_use[i - 1] and g_use[i] >= g_use[i + 1]:
            return float(r[i]), float(g_use[i])
    return None


def box_lengths(rec: dict) -> np.ndarray:
    """Return the (Lx, Ly, Lz) box edge lengths for a run record.

    `rec` is the dict returned by an analyzer's `load_run` (manifest +
    HDF5 fields). Tries (in order): h5 root attribute "box", manifest
    "box", h5 dataset "box". All three should agree; the helper just
    picks the first available so analyzers don't need to triple-check.
    """
    if "box" in rec and rec["box"] is not None:
        box = np.asarray(rec["box"])
        if box.shape == (3, 3):
            return np.array([box[0, 0], box[1, 1], box[2, 2]], dtype=np.float64)
        return np.asarray(box, dtype=np.float64)
    man = rec.get("manifest", {})
    if "box" in man:
        b = np.asarray(man["box"], dtype=np.float64)
        if b.shape == (3, 3):
            return np.array([b[0, 0], b[1, 1], b[2, 2]], dtype=np.float64)
        return b
    raise KeyError("no 'box' available in record (h5 attrs / manifest / dataset)")
