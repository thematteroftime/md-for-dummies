# Auto-discovery registry — design spec

> Status: design draft (brainstorming output)
> Date: 2026-05-10
> Target: agentic-md-for-dummies v0.3.0 cycle
> Replaces: hand-maintained `FORCE_REGISTRY` / `INTEGRATOR_REGISTRY` / `LATTICE_REGISTRY` / `tools/registry.py:_REGISTRY`

## Problem

Today the framework has four manually-curated registries plus two derived files:

| File | Hand-edited content |
|------|---------------------|
| `forces/__init__.py:FORCE_REGISTRY` | dict mapping `force_type` string → class |
| `integrators/__init__.py:INTEGRATOR_REGISTRY` | dict mapping `integrator` string → class |
| `tools/lattices/__init__.py:LATTICE_REGISTRY` | dict mapping lattice name → class |
| `tools/registry.py:_REGISTRY` | single forwarding station mirroring all of the above plus analyzers, plotters, aggregators, visualizers |
| `templates/plan_config.schema.json` | `force_type` and `integrator` enums must match the registries |
| `references/force_types.md` | conventions table at the top must match the registries |

Adding one new force class touches at minimum five places (force file, two registry dicts, schema enum, registry doc table). The 8-step extension process documents this dance, the regression tests `test_registry_local_init_sync` and `test_integrator_schema_enum_synced_with_registry` enforce it after the fact, and a Hard rule in SKILL.md exists specifically because the synchronisation has been broken in past sub-agent runs.

The problem is structural: **the framework grows by adding modules, but the registration mechanism grows linearly in hand-edits per addition.** Both AI and human contributors lose tokens / time / attention on the bookkeeping rather than on physics.

## Goal

Shift registration from "hand-edit five files" to **drop a module file in the right folder, restart, done**. The framework discovers new modules at startup, writes per-folder manifest files that capture current state, and feeds the rest of the workflow (validator, schema, dispatch) from those manifests. AI and human contributors author one new file; the framework handles the bookkeeping.

The four constraints from the requirements discussion:

- One source of truth per folder (`_registry.json` per extension folder, never hand-edited).
- Strict naming alignment so the scanner can verify intent without ambiguity.
- Existing test infrastructure stays — only registration mechanism changes.
- Existing public APIs (`tools.registry.resolve`, `from forces import FORCE_REGISTRY`) keep working so callers don't change.

## Architecture

### Layered view

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 4 — Consumers                                                │
│    scripts/run_experiment.py, scripts/validate_config.py,           │
│    test suite, adapters                                             │
│                                                                     │
│  All consumers call tools.registry.resolve(name) or read            │
│  FORCE_REGISTRY / INTEGRATOR_REGISTRY / LATTICE_REGISTRY            │
│  exactly as today. No consumer changes.                             │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 3 — Aggregator                                               │
│    tools/registry.py                                                │
│      • load_registry(folder_path) → dict[str, type]                 │
│      • resolve(name) → class                                        │
│    Reads _registry.json from each of the 7 extension folders        │
│    and serves the union via the existing resolve() API.             │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 2 — Scanner                                                  │
│    tools/registry/_scanner.py                                       │
│      • scan_folder(folder_path, base_class) → manifest dict         │
│      • update_registry_json(folder_path, manifest)                  │
│      • update_schema_enums()                                        │
│      • check_force_types_md_sections()                              │
│    Triggered by Layer 3 lazily on first access; runs only when      │
│    file mtimes are newer than _registry.json mtime.                 │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 1 — Manifests on disk (per folder)                           │
│    forces/_registry.json                                            │
│    integrators/_registry.json                                       │
│    tools/lattices/_registry.json                                    │
│    tools/analyzers/_registry.json                                   │
│    tools/plotters/_registry.json                                    │
│    tools/aggregators/_registry.json                                 │
│    tools/visualizers/_registry.json                                 │
└─────────────────────────────────────────────────────────────────────┘
```

### Single scanning unit

The same `scan_folder()` logic handles all seven extension types. It is parameterised by:

- the folder path
- the expected base class for that folder's modules (e.g. `forceField` for `forces/`, `IntegratorBase` for `integrators/`)
- a registry-name attribute name (default `REGISTRY_NAME`)

This means seven folders ship with seven calls to the same function, not seven custom scanners.

### `_registry.json` schema

```json
{
  "_schema_version": 1,
  "_folder": "forces",
  "_base_class": "forces.base:forceField",
  "_scanned_at": "2026-05-10T11:42:03+08:00",
  "_python_version": "3.10.19",
  "entries": {
    "lennard_jones": {
      "class_path": "forces.lennard_jones:lennardJones",
      "registry_name": "lennard_jones",
      "ok": true
    },
    "kob_andersen_lj": {
      "class_path": "forces.kob_andersen_lj:KobAndersenLJ",
      "registry_name": "kob_andersen_lj",
      "ok": true
    },
    "broken_example": {
      "class_path": "forces.broken_example:BrokenClass",
      "registry_name": null,
      "ok": false,
      "error_summary": "ImportError: cannot import name 'NotARealThing' from 'numpy'",
      "error_traceback_first_line": "  File \"forces/broken_example.py\", line 4, in <module>"
    }
  }
}
```

The `_` prefixed keys are bookkeeping; the `entries` block is the actual registry. Broken modules appear in `entries` with `"ok": false` and diagnostic fields — they're **listed**, just not **dispatchable**. This lets `tools.registry.resolve("broken_example")` raise a clean error referring back to the manifest, instead of pretending the entry doesn't exist.

## Naming convention (strict, three-way alignment)

For a file `forces/<stem>.py` to be auto-registered:

1. The file stem `<stem>` must match `^[a-z][a-z0-9_]+$` (snake_case, no leading underscore, no dashes).
2. The file must contain **exactly one** public class (not starting with `_`) that subclasses the folder's expected base class.
3. That class must declare a class-level attribute `REGISTRY_NAME = "<stem>"` whose value equals the file stem.

Any deviation is a scanner error pointing at the offending file. The error is loud at scan time, not silent at runtime.

A file with a leading underscore (e.g. `forces/_helper.py`) is skipped entirely — that's the escape hatch for shared code that isn't a registered class. `__init__.py` and `_registry.json` are skipped by convention.

## Schema and force_types.md regeneration

After all seven `_registry.json` files are up to date, the scanner runs two follow-up tasks:

### Schema enum rewrite

`templates/plan_config.schema.json` has two enums that the scanner regenerates:

- `properties.force_type.enum` ← keys of `forces/_registry.json` where `ok=true`
- `properties.integrator.enum` ← keys of `integrators/_registry.json` where `ok=true`

The scanner only rewrites the `enum` arrays. The surrounding schema structure (top-level shape, `if/then` conditional blocks, property type definitions) is preserved. Implementation: parse JSON, mutate the two enum arrays, write back with consistent formatting.

The `if/then` conditionals remain manually maintained in v1. Promoting them to auto-generation is a v2 enhancement that requires each force class to declare its required-fields signature; doable but out of scope here.

### force_types.md conventions table

The top-of-file *Conventions table* (which lists each force_type's `N`-meaning, default IC, ndim, units_regime) is regenerated from the per-folder manifests plus class metadata.

Per-section bodies (per-force-type pre-flight rules, examples, prose) stay manual. The scanner emits a warning if a force_type appears in `forces/_registry.json` but no `## N. <force_type>` section exists in `force_types.md` — that's a real documentation gap the human author must fill.

## Trigger and caching

The scanner is invoked from `tools.registry` at module import time:

```python
# tools/registry.py
def _ensure_fresh():
    for folder in _EXTENSION_FOLDERS:
        if _folder_dirty(folder):
            _scanner.scan_folder(folder)
    _scanner.regenerate_schema_enums()

_ensure_fresh()  # at module load

def resolve(name):
    ...  # reads pre-loaded _REGISTRY (now populated from JSON)
```

`_folder_dirty(folder)` returns True if any `.py` file in the folder has mtime newer than `_registry.json`'s mtime. If all `.py` files are older, the JSON is current and `_ensure_fresh` is a no-op (a few `os.stat` calls — sub-millisecond).

`_ensure_fresh` always loops over **all seven** folders, not just the one a caller is asking about. This is intentional: the schema enum and `force_types.md` conventions table depend on the union of all folders' state, so a partial scan would emit a partial schema. With mtime caching, the seven-folder loop is essentially free when nothing changed.

After the seven-folder loop completes, if any folder was rescanned, the schema-enum rewrite and conventions-table rewrite run as the final two steps before `_ensure_fresh` returns. This means the order of triggers (`from forces import FORCE_REGISTRY` vs `from integrators import BAOABLangevin`) doesn't matter — first one to run brings everything up to date, subsequent imports in the same process see fully-fresh state.

The experience: add a file → restart → first registry-touching import does the rescan (~0.5 s for the affected folder, plus negligible time for the six fresh ones) → all subsequent imports in the same Python process are instant.

The CLI `python scripts/scan_registry.py` exists as a forced rescan, useful for CI / pre-commit / debugging. It scans all folders unconditionally and prints a diff of changed entries. A `--check` flag runs in dry-run mode (no writes) and exits non-zero if it would have written anything — that's the CI gate.

## Failure modes and recovery

| Failure | Scanner behaviour | Runtime behaviour |
|---------|-------------------|-------------------|
| File fails to import | Records `ok: false` + error summary | `resolve("<name>")` raises with manifest's error message |
| Filename violates naming convention | Records as `_skipped` with reason | Module never appears in any registry |
| Class lacks `REGISTRY_NAME` | Records `ok: false` + reason | Same |
| `REGISTRY_NAME` ≠ file stem | Records `ok: false` + reason | Same |
| Multiple base-class subclasses in one file | Records `ok: false` + lists candidates | Same |
| Zero base-class subclasses | Records as `_skipped` with reason | (Treated as helper module) |
| `_registry.json` missing entirely | Created on first scan | n/a |
| `_registry.json` corrupted JSON | Renamed to `.corrupt.<timestamp>`, fresh one written | n/a |

The unifying rule: scanner is **forgiving** (records and continues), `resolve()` is **strict** (only succeeds for `ok: true` entries).

## Migration

The migration is a hard cut, not a parallel-run. The four hand-curated dicts are replaced by runtime-built dicts that read from disk:

```python
# forces/__init__.py — before
FORCE_REGISTRY: dict[str, type] = {
    "lennard_jones":          lennardJones,
    "er_plasma":              ERPotential,
    ...
}

# forces/__init__.py — after
from tools.registry import load_registry
FORCE_REGISTRY = load_registry("forces")  # reads forces/_registry.json
```

The public API (`from forces import FORCE_REGISTRY`) is unchanged. Callers continue to work without modification. The same pattern applies to `integrators/__init__.py:INTEGRATOR_REGISTRY` and `tools/lattices/__init__.py:LATTICE_REGISTRY`.

`tools/registry.py:_REGISTRY` similarly becomes a function-backed dict whose contents come from the union of all per-folder manifests.

The two regression tests change:

- `test_registry_local_init_sync` is **deleted** — its job (catching drift between forwarding station and local registries) is now structurally impossible because both come from the same JSON files.
- `test_integrator_schema_enum_synced_with_registry` is **simplified** to assert that the schema enum equals the registry keys; both come from the same scan, so this becomes a tautology check that catches regression in the schema rewriter.

A new test, `test_registry_matches_disk_state`, asserts that running `scan_registry.py --check` (dry-run mode) finds zero diff — i.e. the committed `_registry.json` files are in sync with the actual `.py` files in the folders. This catches "developer added file but didn't restart, so manifest is stale".

## Class metadata convention (extends current attribute usage)

Each registered class declares a small set of class-level attributes. Most are already in use today; the new attribute is `REGISTRY_NAME`.

For a force class:

```python
@ti.data_oriented
class KobAndersenLJ(forceField):
    REGISTRY_NAME       = "kob_andersen_lj"     # NEW; must match file stem
    requires_full_list  = True                  # already present
    PREFLIGHT_FIELDS    = ("T0", "rho", "N", "steps")  # already present

    def __init__(self, ...):
        ...
```

For an integrator class:

```python
@ti.data_oriented
class BAOABLangevin(IntegratorBase):
    REGISTRY_NAME    = "baoab_langevin"          # NEW; must match file stem
    REQUIRED_KWARGS  = ("timeStep", "T_target")  # already present
    OPTIONAL_KWARGS  = ("nu",)                   # already present

    def __init__(self, ...):
        ...
```

The existing `SCHEME_NAME` attribute on integrator classes is dropped during migration. It served the same role as the new `REGISTRY_NAME` attribute and keeping both invites confusion. The scanner emits a one-time deprecation warning if it sees a class that declares only `SCHEME_NAME` without `REGISTRY_NAME`, listing the file path so the migration can be done in one pass.

For an analyzer / plotter / aggregator / visualizer / lattice class, only `REGISTRY_NAME` is required. The class still subclasses its base contract (`PaperAnalyzer.full_analysis`, `Plotter.render`, etc.).

## Templates updated

Six code templates that ship with the skill gain a `REGISTRY_NAME = "<name>"` line in their scaffold:

- `templates/force_class.py.template`
- `templates/integrator.py.template`
- `templates/analyzer.py.template`
- `templates/plotter.py.template`
- `templates/aggregator.py.template`
- `templates/visualizer.py.template`

A new template `templates/lattice.py.template` is added (the lattice package is currently the one extension type without a template), so the seven scanned folders all have parallel scaffolds.

The 8-step force-class extension and 9-step integrator extension flows in `references/force_types.md` keep the same step counts but several sub-steps within them disappear:

- Step 1's "register in `forces/__init__.py:FORCE_REGISTRY` AND `tools/registry.py:_REGISTRY`" collapses to just "save the file with the right naming convention".
- Step 5's "add to `force_type` enum in schema" goes away; the scanner does it.
- Step 6's "add a row to the conventions table at the top of `force_types.md`" goes away; the scanner does it.
- Step 7's "register in `tools/registry.py:_REGISTRY`" goes away.
- Step 8's "register both in `tools/registry.py:_REGISTRY`" goes away.

What remains in the 8-step force flow: the force class itself, tests, adapter, dispatcher branch in `_invoke_md`, validator branch in `check_force_type_specific`, the per-force-type prose body in `force_types.md`, the analyzer, the plotter / aggregator. Each step is shorter; the count stays 8 because the steps map to genuinely distinct artefacts. Same shape for the 9-step integrator flow.

## Testing strategy

Three test layers, all already-existing pattern adapted:

1. **Unit tests for the scanner** (`tests/test_scanner.py`, new): construct a temp folder with valid + invalid files, invoke `scan_folder()`, assert the output manifest has the expected `entries` dict. Cover every failure mode in the table above.

2. **Integration test for the dispatch path** (`tests/test_skill_regression.py`, modified): assert that for every `force_type` in the schema enum, `tools.registry.resolve(name)` returns a class that subclasses `forceField`. Same for integrator, lattices, analyzers, plotters, aggregators, visualizers.

3. **Cleanliness test** (`tests/test_scanner.py`, new): run `scan_registry.py --check`; assert exit 0 (no diff between disk state and committed `_registry.json` files).

The existing 60-test baseline minus the two redundant tests plus the three new tests gives ~61 tests. Same wall time.

## Out of scope (explicit non-goals for v1)

- Auto-generating the `if/then` conditional blocks in `plan_config.schema.json`. The scanner only rewrites the two enum arrays.
- Auto-generating prose sections of `force_types.md`. Only the conventions table.
- Hot-reload during a running framework. Scanner runs at module import; in-process changes need a Python restart.
- Per-class versioning / deprecation in the manifest. v1 just tracks "registered now" or "registered now but broken".
- A Web UI / TUI for browsing the registry. CLI `scripts/scan_registry.py --list` is the discovery interface.
- Cross-package plugin discovery via `importlib.metadata.entry_points`. The scope is the local repo's seven folders only.

## Risks and open questions

| Risk | Mitigation |
|------|------------|
| Import-time cost grows with module count | mtime-based caching makes idle imports near-free; full scan only on file change |
| A broken module in `forces/` blocks the whole framework startup | Scanner is forgiving (records error, continues); only `resolve()` of that specific name fails |
| Developer commits a `_registry.json` that doesn't match the `.py` files (e.g. forgot to restart, edited manually) | `test_registry_matches_disk_state` regression test catches it on next CI run; pre-commit hook can run `scan_registry.py --check` |
| Two folders accidentally use the same registry name (e.g. `forces/lennard_jones.py` and `tools/visualizers/lennard_jones.py`) | Aggregator (Layer 3) detects collision, raises with both file paths; in practice extension types are namespaced by folder so this is unlikely |
| Schema rewrite mangles the JSON (formatting differences, comment loss) | JSON Schema doesn't have comments; rewriter uses `json.dumps(indent=2, sort_keys=False)` to keep the file diff-clean |

## Implementation order (rough sketch for writing-plans)

1. Build `tools/registry/_scanner.py` with `scan_folder()` standalone — pure unit-test target.
2. Wire the scanner into `tools/registry.py` with the `_ensure_fresh()` lazy trigger.
3. Migrate `forces/__init__.py` to `FORCE_REGISTRY = load_registry("forces")`. Generate first `forces/_registry.json` by running the scanner.
4. Repeat (3) for `integrators/`, `tools/lattices/`.
5. Add `REGISTRY_NAME` attribute to every existing force class, integrator class, lattice class. Run scanner; verify all entries are `ok: true`.
6. Migrate `tools/registry.py:_REGISTRY` to read from all seven manifests. Verify aggregator-side tests (analyzer / plotter / aggregator / visualizer) still pass.
7. Add schema-enum rewrite step to scanner. Run scanner; verify schema validates existing configs.
8. Add force_types.md conventions-table rewrite step. Verify diff is clean.
9. Replace `test_registry_local_init_sync` with `test_registry_matches_disk_state`. Update `test_integrator_schema_enum_synced_with_registry` accordingly.
10. Add unit tests for the scanner (per-failure-mode).
11. Update SKILL.md, force_types.md `§4` and `§5b` extension flows to reflect the new (shorter) step counts.
12. Update README.md and README_zh.md "Human-developer walkthrough" sections to describe the new flow.

End of design.
