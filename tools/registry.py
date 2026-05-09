"""tools/registry.py — name → class lookup for config-driven dispatch.

Lets `configs/plan_*.json` say:

    "analyze":   {"class": "PRXAnalyzer",  "params": {...}},
    "visualize": {"class": "TaichiTrajectoryViz", "enabled": true, "params": {...}},

and `scripts/run_experiment.py` will resolve those names to actual classes
without needing a `match` statement per class. Users who add a new
analyzer/visualizer just register it here (one line) and reference it by
name in their config.

Resolution rules:
- If `class_name` contains a dot (e.g. `myproj.analyzers.MyAnalyzer`), import
  the dotted path as a fully-qualified module path.
- Otherwise, look up `class_name` in the local `_REGISTRY` dict.

Convention:
- Analyzer classes implement `.full_analysis(run_dir, **params) -> dict`.
- Visualizer classes implement `.render(run_dir_or_h5, **params) -> None`
  (interactive) or `.record(out_path, **params) -> None` (mp4).
"""
from __future__ import annotations
import importlib
from typing import Any, Type

# Registered classes. ONE forwarding station for the whole framework: every
# extension point — forces, lattices, analyzers, plotters, aggregators,
# visualizers — registers here. To find what's wired up, read this file.
#
# When adding any new class, also register it in the matching package's local
# __init__.py (e.g. forces/__init__.py:FORCE_REGISTRY) so direct-import users
# see it too. The two registries kept in sync is the framework contract.
_REGISTRY: dict[str, str] = {
    # forces (pair potentials; force_type strings used in configs/plan_*.json)
    "lennardJones":           "forces.lennard_jones:lennardJones",
    "ERPotential":            "forces.er_potential:ERPotential",
    "HertzianNonreciprocal":  "forces.hertzian_nonreciprocal:HertzianNonreciprocal",
    "KobAndersenLJ":          "forces.kalj:KobAndersenLJ",
    # lattices (initial-condition generators)
    "square_2d":              "tools.lattices.square_2d:SquareLattice2D",
    "triangular_2d":          "tools.lattices.triangular_2d:TriangularLattice2D",
    "octagonal_2d":           "tools.lattices.octagonal_2d:OctagonalLattice2D",
    "simple_cubic_3d":        "tools.lattices.simple_cubic_3d:SimpleCubicLattice3D",
    # analyzers (per-run)
    "PRXAnalyzer":            "tools.analyzers.prx:PRXAnalyzer",
    "ERAnalyzer":             "tools.analyzers.er:ERAnalyzer",
    "PedersenAnalyzer":       "tools.analyzers.pedersen:PedersenAnalyzer",
    # plotters (per-run figures)
    "PRXPlotter":             "tools.plotters.prx:PRXPlotter",
    "PedersenPlotter":        "tools.plotters.pedersen:PedersenPlotter",
    # aggregators (cross-run; Phase 4 dispatcher resolves these)
    "PRXAggregator":          "tools.aggregators.prx:PRXAggregator",
    "ERAggregator":           "tools.aggregators.er:ERAggregator",
    "PedersenAggregator":     "tools.aggregators.pedersen:PedersenAggregator",
    # visualizers (interactive / video)
    "TaichiTrajectoryViz":    "tools.visualizers.taichi_traj:TaichiTrajectoryViz",
    # runner
    "ExperimentRunner":       "tools.runner:ExperimentRunner",
}


def resolve(class_name: str) -> Type[Any]:
    """Resolve a class name to an actual class object.

    >>> cls = resolve("PRXAnalyzer")
    >>> cls.PAPER_SLOPE  # class attribute
    0.6666666666666666
    """
    if "." in class_name and ":" in class_name:
        module_path, attr = class_name.rsplit(":", 1)
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    if class_name in _REGISTRY:
        target = _REGISTRY[class_name]
        module_path, attr = target.split(":", 1)
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise KeyError(
        f"unknown class '{class_name}' — register it in tools/registry.py:_REGISTRY "
        f"or pass a fully-qualified 'package.module:ClassName' string. "
        f"known: {sorted(_REGISTRY)}"
    )


def register(class_name: str, target: str) -> None:
    """Register a new class at runtime. Useful for tests / extensions."""
    _REGISTRY[class_name] = target


def known() -> list[str]:
    """List all registered names."""
    return sorted(_REGISTRY)
