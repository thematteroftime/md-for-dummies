"""Lattice IC generator package.

Each lattice has a class with `.generate(N, params) -> (positions[N,3], box[3,3])`.
See `_template.py` for the contract; see `tools/registry.py:_REGISTRY` for
the forwarding-station view that includes lattices alongside forces /
analyzers / plotters.

Default IC by ndim (used when adapter does not specify):
- ndim=2 → square_2d
- ndim=3 → simple_cubic_3d

Adapters call:
    from tools.lattices import LATTICE_REGISTRY
    LatticeCls = LATTICE_REGISTRY[design_doc["initial_state"]]
    positions, box = LatticeCls.generate(N, params)
"""
from tools.lattices.square_2d import SquareLattice2D
from tools.lattices.triangular_2d import TriangularLattice2D
from tools.lattices.octagonal_2d import OctagonalLattice2D
from tools.lattices.simple_cubic_3d import SimpleCubicLattice3D


LATTICE_REGISTRY: dict[str, type] = {
    "square_2d":          SquareLattice2D,
    "triangular_2d":      TriangularLattice2D,
    "octagonal_2d":       OctagonalLattice2D,    # stub — raises NotImplementedError
    "simple_cubic_3d":    SimpleCubicLattice3D,
}


# Default lattice key per ndim (consulted by adapters when design doc omits
# `initial_state`). Adapters wishing a paper-specific default override this.
DEFAULT_LATTICE_BY_NDIM: dict[int, str] = {
    2: "square_2d",
    3: "simple_cubic_3d",
}


__all__ = [
    "SquareLattice2D",
    "TriangularLattice2D",
    "OctagonalLattice2D",
    "SimpleCubicLattice3D",
    "LATTICE_REGISTRY",
    "DEFAULT_LATTICE_BY_NDIM",
]
