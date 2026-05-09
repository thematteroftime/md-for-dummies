"""Force-field package: one file per registered pair-potential.

Structure:
- `base.py`       — `forceField` abstract parent
- `<paper>.py`    — concrete potential, one per paper / model
- `__init__.py`   — local FORCE_REGISTRY mapping the `force_type` string
                    (used in configs/plan_*.json) to the concrete class

External code SHOULD prefer one of:
  - `from forces import HertzianNonreciprocal`     (direct, by class name)
  - `from forces import FORCE_REGISTRY`            (config-driven dispatch)
  - `tools.registry.resolve("HertzianNonreciprocal")` (single forwarding station)

When adding a new force class:
  1. Write `forces/<your_force>.py` with class subclassing `forceField`
  2. Export it here (line in `from ... import` block AND in FORCE_REGISTRY)
  3. Mirror the registration in `tools/registry.py:_REGISTRY` for the
     forwarding-station view
  4. Add the matching `force_type` enum value in
     `.claude/skills/paper-to-experiment/templates/plan_config.schema.json`
  5. Document in `.claude/skills/paper-to-experiment/references/force_types.md`

See SKILL §"Adding a new force type" for the full 8-step extension flow.
"""
from forces.base import forceField
from forces.lennard_jones import lennardJones
from forces.er_potential import ERPotential
from forces.hertzian_nonreciprocal import HertzianNonreciprocal
from forces.kalj import KobAndersenLJ


# Maps the `force_type` string used in configs/plan_*.json to the class.
# Adapter scripts may resolve via FORCE_REGISTRY[exp["force_type"]] when
# they want config-driven dispatch instead of direct class import.
FORCE_REGISTRY: dict[str, type] = {
    "lennard_jones":           lennardJones,
    "er_plasma":               ERPotential,
    "hertzian_nonreciprocal":  HertzianNonreciprocal,
    "kalj":                    KobAndersenLJ,
}


__all__ = [
    "forceField",
    "lennardJones",
    "ERPotential",
    "HertzianNonreciprocal",
    "KobAndersenLJ",
    "FORCE_REGISTRY",
]
