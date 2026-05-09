"""Template + shared lattice helpers.

This module is two things in one:

1. **Template** — `_LatticeTemplate` defines the contract every concrete
   lattice in `tools/lattices/` follows. New lattices subclass it (or just
   match its API) and provide `generate(N, params) -> (positions, box)`.

2. **Paper-agnostic helpers** — `assign_species_random(N, fractions, seed)`
   for binary / multi-species papers (KA-LJ, generalised Kob-Andersen, etc.)
   to randomly partition N atoms into species groups with a deterministic seed.

# Lattice contract

Every lattice in `tools/lattices/` MUST implement a class with this signature:

    class <Name>Lattice<Dim>:
        ndim: int   # 2 or 3
        name: str   # registry key (e.g. "square_2d")

        @classmethod
        def generate(cls, N: int, params: dict) -> tuple[np.ndarray, np.ndarray]:
            '''Return (positions[N,3], box[3,3]).'''

- `positions[N, 3]`: (x, y, z) per atom; z=0 for ndim=2 lattices.
- `box[3, 3]`: row-major 3×3 matrix; row k is the k-th cell vector.
  For ndim=2: box[0], box[1] span the 2D plane; box[2] = (0, 0, Lz)
  with Lz set from `params["Lz"]` or a sensible default
  (caller is responsible for ensuring Lz ≥ cutoffNegh; see
  atomSystemClass.addNegh contract).
- `params` keys (per-lattice; document in the subclass docstring):
  - `density`         (float) — number per unit volume (3D) or area (2D)
  OR
  - `lattice_constant` (float) — cell edge length
  - `box_extent` (3-tuple, optional) — explicit box size override

Lattices are dispatched via `tools.registry.resolve(name)` from the single
forwarding station and via `tools.lattices.LATTICE_REGISTRY` for direct use.

Default IC by ndim (used when `physics_design.md §3 initial_state` is omitted):
- ndim=2 → "square_2d"
- ndim=3 → "simple_cubic_3d"

When adding a new lattice:
1. Implement `<Name>Lattice<Dim>` in `tools/lattices/<name>_<dim>.py`
2. Export in `tools/lattices/__init__.py:LATTICE_REGISTRY`
3. Mirror in `tools/registry.py:_REGISTRY` for the forwarding-station view
4. Add a row to `tests/test_lattices.py`

# Species-tagging helper

For papers with mixed species (binary LJ, KA, ternary mixtures), generate
positions with one of the lattices then assign species ids via
`assign_species_random`. Adapters write the resulting `groups` array to
the lattice .xyz first column for `read_inputPos` / `AtomSystem.initData`
to consume.
"""
from __future__ import annotations
from typing import Sequence

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


def assign_species_random(N: int, fractions: Sequence[float], seed: int = 0) -> np.ndarray:
    """Return a length-N int32 array of group ids in {1, 2, ...} matching
    the requested fractions, randomly permuted with a deterministic seed.

    Example: a KA 80:20 mixture of N=1000 atoms uses
        groups = assign_species_random(1000, [0.8, 0.2], seed=0)
    which gives 800 ones and 200 twos in a deterministic random order.

    Round-off: `round(fraction · N)` per group; the largest group absorbs
    the rounding remainder so total == N exactly.
    """
    fractions_arr = np.asarray(fractions, dtype=np.float64)
    if abs(fractions_arr.sum() - 1.0) > 1e-9:
        raise ValueError(f"fractions must sum to 1.0 (got {fractions_arr.sum()})")
    counts = np.round(fractions_arr * N).astype(np.int64)
    diff = int(N - counts.sum())
    if diff != 0:
        counts[int(np.argmax(counts))] += diff
    groups = np.empty(N, dtype=np.int32)
    pos = 0
    for gid, k in enumerate(counts, start=1):
        groups[pos:pos + k] = gid
        pos += int(k)
    rng = np.random.default_rng(int(seed))
    rng.shuffle(groups)
    return groups
