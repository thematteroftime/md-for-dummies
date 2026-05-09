"""Base class for all pair-potential force fields.

Every force in `forces/` subclasses `forceField`, which handles the boilerplate
of binding to an `AtomSystem` + `searchBox`, zeroing forces each step, and
dispatching the per-pair update kernel based on `reciprocal` flag.

Subclasses MUST define:
- `requires_full_list: bool` — True if neighbour list contains both (i,j) and (j,i)
- `updateOneF_reciprocal` or `updateOneF_nonreciprocal` (the @ti.func)
- `__init__(self, ...)` with paper parameters

Subclasses MAY define:
- `PREFLIGHT_FIELDS: tuple[str, ...]` — campaign config field names that
  ResourceEstimator should highlight for this force_type. Used by
  `tools.resources.print_preflight` for force-type-aware preflight printing.
- `register(self, atomSystem, searchBox)` — override only when the force has
  unit-dependent constants that must be resolved at register-time
  (e.g. `cs.UNITS.KE_E2`); MUST end with `super().register(...)`.
"""
from constSet import *


@ti.data_oriented
class forceField:
    requires_full_list: bool = False    # subclasses override
    PREFLIGHT_FIELDS: tuple = ()        # subclasses override (used by tools.resources)

    def register(self, atomSystem, searchBox):
        self.cutoffSquare = atomSystem.cutoff * atomSystem.cutoff
        self.atomSystem = atomSystem
        self.searchBox = searchBox
        self.reciprocal = getattr(self, 'reciprocal', True)
        # Propagate requires_full_list to the searchBox so the neighbour builder
        # always uses the correct list type, regardless of registration order.
        searchBox.full_list = bool(self.requires_full_list)
        return

    @ti.func
    def calForce(self):
        pass

    @ti.func
    def calPotential(self):
        pass

    @ti.func
    def updateOneF_reciprocal(self, i: ti.i32, j: ti.i32):
        pass

    @ti.func
    def updateOneF_nonreciprocal(self, i: ti.i32, j: ti.i32):
        pass

    @ti.kernel
    def updateAllF_zero(self):
        for i in range(self.atomSystem.num_atoms):
            self.atomSystem.force[i] = ti.Vector([0.0, 0.0, 0.0])
            self.atomSystem.pe_per_atom[i] = 0.0

    @ti.kernel
    def updateAllF_compute(self):
        ti.loop_config(block_dim=128)
        for i in range(self.atomSystem.num_atoms):
            for jj in range(self.atomSystem.nNum[i]):
                j_idx = self.atomSystem.nList[i, jj]
                if j_idx >= 0 and j_idx < self.atomSystem.num_atoms:
                    if ti.static(self.reciprocal):
                        self.updateOneF_reciprocal(i, j_idx)
                    else:
                        self.updateOneF_nonreciprocal(i, j_idx)

    def updateAllF(self):
        self.updateAllF_zero()
        self.updateAllF_compute()
        return
