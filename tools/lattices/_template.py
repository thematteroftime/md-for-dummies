"""Template for new lattice generators.

Every lattice in `tools/lattices/` MUST implement a class with this signature:

    class <Name>Lattice<Dim>:
        ndim: int   # 2 or 3
        name: str   # registry key (e.g. "square_2d")

        @classmethod
        def generate(cls, N: int, params: dict) -> tuple[np.ndarray, np.ndarray]:
            '''Return (positions[N,3], box[3,3]).'''

Contract:
- `positions[N, 3]`: (x, y, z) per atom; z=0 for ndim=2 lattices.
- `box[3, 3]`: row-major 3×3 matrix; row k is the k-th cell vector.
  For ndim=2: box[0], box[1] span the 2D plane; box[2] = (0, 0, Lz)
  with Lz set from `params["Lz"]` or — if absent — a sensible default
  (caller is responsible for ensuring Lz ≥ cutoffNegh; see
  atomSystemClass.addNegh contract).
- `params` keys (per-lattice; document in the subclass docstring):
  - `density`         (float) — number per unit volume (3D) or area (2D)
  OR
  - `lattice_constant` (float) — cell edge length
  - `box_extent` (3-tuple, optional) — explicit box size override

Lattices are dispatched via `tools.registry.resolve(name)` from a single
forwarding station and via `tools.lattices.LATTICE_REGISTRY` for direct use.

Default IC by ndim (used when `physics_design.md §3 initial_state` is omitted):
- ndim=2 → "square_2d"
- ndim=3 → "simple_cubic_3d"

When adding a new lattice:
1. Implement `<Name>Lattice<Dim>` here
2. Export in `tools/lattices/__init__.py:LATTICE_REGISTRY`
3. Mirror in `tools/registry.py:_REGISTRY` for the forwarding-station view
4. Add a row to `tests/test_lattices.py`
"""
import numpy as np


class _LatticeTemplate:
    """Base type-hint stub. Subclasses override generate()."""
    ndim: int = 2
    name: str = "_template"

    @classmethod
    def generate(cls, N: int, params: dict) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError(
            f"{cls.__name__} is a template — subclass and implement generate()"
        )
