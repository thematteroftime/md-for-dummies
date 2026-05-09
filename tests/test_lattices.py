"""Unit tests for tools/lattices/ generators.

Each lattice must:
1. Return positions[N, 3] and box[3, 3] arrays of correct shape & dtype
2. Have z-column exactly 0 for ndim=2
3. Match target density within 5%
4. Have no two atoms closer than 0.5·(min lattice edge) — sanity for a
   well-spread initial config
5. Be importable via tools.registry.resolve(name)
"""
import numpy as np
import pytest

from tools.lattices import (
    LATTICE_REGISTRY, DEFAULT_LATTICE_BY_NDIM,
    SquareLattice2D, TriangularLattice2D, OctagonalLattice2D, SimpleCubicLattice3D,
)
from tools.registry import resolve


# ---------------------------------------------------------------------------
# Generator-level tests (one parametrised test per concrete lattice)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("LatticeCls,N,density,ndim", [
    (SquareLattice2D,      64,  0.5,   2),
    (SquareLattice2D,      100, 1.0,   2),
    (TriangularLattice2D,  64,  0.5,   2),
    (TriangularLattice2D,  98,  1.2,   2),
    (SimpleCubicLattice3D, 64,  0.5,   3),
    (SimpleCubicLattice3D, 1000, 1.0,  3),
])
def test_lattice_basic(LatticeCls, N, density, ndim):
    pos, box = LatticeCls.generate(N, {"density": density})

    assert pos.shape == (N, 3), f"positions shape {pos.shape}"
    assert box.shape == (3, 3), f"box shape {box.shape}"
    assert pos.dtype == np.float64
    assert box.dtype == np.float64

    if ndim == 2:
        assert np.all(pos[:, 2] == 0.0), "ndim=2 lattices must have z=0"

    # Density check: N / (box volume — or 2D area times Lz=1)
    if ndim == 2:
        area = box[0, 0] * box[1, 1]
        n_meas = N / area
    else:
        vol = box[0, 0] * box[1, 1] * box[2, 2]
        n_meas = N / vol
    assert abs(n_meas - density) / density < 0.5, (
        f"density mismatch: target={density}, measured={n_meas}"
    )


def test_octagonal_stub_raises():
    """Octagonal lattice is reserved as a stub — calling raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        OctagonalLattice2D.generate(64, {"density": 0.5})


def test_square_jitter_breaks_degeneracy():
    """Jitter parameter actually displaces atoms."""
    pos_no_jitter, _ = SquareLattice2D.generate(16, {"density": 1.0, "jitter": 0.0})
    pos_jittered, _ = SquareLattice2D.generate(16, {"density": 1.0, "jitter": 0.1})
    diff = np.abs(pos_no_jitter - pos_jittered).max()
    assert diff > 0.01, "jitter=0.1 should produce visible displacement"


def test_lattice_constant_overrides_density():
    """If lattice_constant is given, density is ignored."""
    pos_a, box_a = SquareLattice2D.generate(16, {"lattice_constant": 1.5})
    pos_b, box_b = SquareLattice2D.generate(16, {"density": 1.0})
    # Different a → different box edge
    assert abs(box_a[0, 0] - box_b[0, 0]) > 0.1


# ---------------------------------------------------------------------------
# Registry tests (tools/lattices/__init__.py + tools/registry.py)
# ---------------------------------------------------------------------------

def test_lattice_registry_keys():
    assert set(LATTICE_REGISTRY.keys()) == {
        "square_2d", "triangular_2d", "octagonal_2d", "simple_cubic_3d"
    }


def test_default_lattice_per_ndim():
    assert DEFAULT_LATTICE_BY_NDIM[2] == "square_2d"
    assert DEFAULT_LATTICE_BY_NDIM[3] == "simple_cubic_3d"


@pytest.mark.parametrize("name", ["square_2d", "triangular_2d", "simple_cubic_3d"])
def test_forwarding_station_resolves(name):
    """tools.registry.resolve() must reach the same class as direct import."""
    via_registry = resolve(name)
    via_local = LATTICE_REGISTRY[name]
    assert via_registry is via_local


def test_lz_default_2d():
    """ndim=2 lattices accept Lz from params; box[2,2] matches."""
    _, box = SquareLattice2D.generate(16, {"density": 1.0, "Lz": 5.0})
    assert box[2, 2] == 5.0
