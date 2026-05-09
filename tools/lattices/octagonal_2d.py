"""2D 8-fold symmetric quasicrystal (Ammann-Beenker tiling) — STUB.

This is a placeholder. A proper Ammann-Beenker implementation requires
cut-and-project from Z⁴ via the four primitive vectors at 45° spacing,
combined with an internal-space window filter. The framework reserves the
slot so callers can request `octagonal_2d` from the registry once it's
implemented.

When implementing:
- Reference: Beenker, "Algebraic theory of non-periodic tilings of the
  plane" (1982); standard cut-and-project on Z⁴.
- Acceptance test: tessellation has exact 8-fold rotational symmetry
  about origin (rotate by 45° → matches itself); pair distances cluster
  near {1, √(2-√2), √2, ...}·a.

Contract preserved: same `generate(N, params) -> (positions, box)` signature
as other lattices, so swapping the impl in won't require dispatcher changes.
"""
import numpy as np


class OctagonalLattice2D:
    ndim = 2
    name = "octagonal_2d"

    @classmethod
    def generate(cls, N: int, params: dict) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError(
            "OctagonalLattice2D (Ammann-Beenker quasicrystal) is reserved as a "
            "registry slot but not yet implemented. Use square_2d or "
            "triangular_2d for now, or implement cut-and-project from Z⁴ "
            "(see module docstring). Tracking: when a paper actually needs "
            "this, the implementer should add the algorithm + tests in one PR."
        )
