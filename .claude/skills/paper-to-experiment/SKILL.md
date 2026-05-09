---
name: paper-to-experiment
description: Use when the user wants to reproduce a physics paper (or part of one) in this MD framework. Takes a paper PDF/text/idea, walks through a fixed design template, validates against the schema, and emits a runnable configs/plan_*.json. Used at the start of any new reproduction campaign.
---

# Paper → Experiment Skill

You are designing a simulation campaign for the `MD_test1` framework. Your job is to turn a physics paper (or a focused idea derived from one) into a validated `configs/plan_<topic>.json` that `python scripts/run_experiment.py` can launch directly.

**This skill is a gate, not a free-form writer.** You follow the template, the schema, and the registry. You do not invent fields. You surface ambiguity to the user before writing JSON.

---

## Hard rules (do not break)

1. **Read the registry first.** Open `references/force_types.md` and read it BEFORE proposing any field. The skill must work only with registered `force_type` strings unless you walk the user through §3 (adding a new force type).

2. **Citations are mandatory.** Every observable in §1 of the design doc must cite a paper Eq. or Fig. number. If a number isn't in the paper, mark it with `*` and explain in §11 (validation plan). No bare claims like "expected to converge."

3. **Smoke before production.** Every config you emit must have `pipeline.smoke=true` and `smoke_steps ≥ 100` unless the user explicitly asks otherwise (and you note the override in `_comment`).

4. **Validation gate.** Before announcing the config is ready, run `python scripts/validate_config.py <path> --strict`. If it returns non-zero, fix the issues and re-run; do not hand off a failing config.

5. **Cost budget.** If the validator reports `single-run wall > 24 hr` or `VRAM > 8 GB`, propose smaller `N` or `steps` rather than asking the user to approve a 1-day GPU burn.

6. **No silent invention.** If a paper parameter is missing from the source you were given, ASK in §10 (decision log) — don't fill in a "reasonable guess." Acceptable: `T0=0.3` because §II of paper says so. Unacceptable: `T0=0.3` because it worked for E1.

7. **Reuse before extending.** If the paper's force resembles `HertzianNonreciprocal` or `ERPotential`, reuse it. Only propose a new force class if §2 of the design doc cites a paper equation that genuinely cannot be expressed by the existing classes.

---

## Process flow

```
1. Acknowledge → 2. Read paper → 3. Fill design doc → 4. User approves
                                                        ↓
                       7. Hand off ←  6. Validate ← 5. Emit JSON
```

### Step 1 — Acknowledge

Announce: *"Using paper-to-experiment skill. Will walk through the fixed template, then emit a validated config."*

Ask the user (if not already provided) where the paper is:
- PDF path under `papers/`?
- Already-extracted text/notes under `docs/`?
- Just an idea/excerpt in the message?

Do NOT proceed until you can name a source.

### Step 2 — Read paper / source

Read in this order:
1. The paper PDF (or rendered pages under `papers/rendered/`).
2. `references/force_types.md` (registry).
3. The two existing examples under `references/examples/` to see what a finished design looks like.
4. Any prior `docs/<TOPIC>_design.md` or `docs/PRX_paper_notes.md` if this is a continuation.

Identify:
- which `force_type` to use (or whether a new one is needed)
- which physics observables the paper reports as primary results
- which figures of the paper we are claiming to reproduce
- any analytical fingerprints (dimensionless numbers from appendices) you can compute pre-simulation

### Step 3 — Fill design doc

Copy `templates/physics_design.md` to `docs/specs/YYYY-MM-DD-<topic>-design.md` and fill it section by section. Replace EVERY `<...>` placeholder. If a section truly does not apply, write `N/A — <reason>` (do not delete).

Keep §1 (observables) as the spine. Everything else flows from the observables: §3 setup must be sufficient to measure §1; §4 sweep must vary the dependence claimed in §1; §6 pass criteria must declare numeric thresholds for §1.

For §2 (force field):
- If existing class works: paste the registry entry's required fields verbatim, then list which simulation parameters from §3 you need.
- If new class needed: complete §2a in full. Stop and surface to user — new force class requires test files and dispatcher updates that are out of skill scope; user must approve the extension first.

For §4 (sweep dimensions):
- Total runs ≤ 12 by default. If more needed, split into Plan A / Plan B and emit two configs.
- Each sweep value must be motivated by a paper passage (cite it).

For §7 (costs):
- Estimate from the closest prior run if available (read `outputFiles/*/manifest.json`).
- If the paper run length cannot be matched within budget, surface the trade-off in §10 and propose a reduced version.

### Step 4 — User approval

Save the design doc and ask the user to review it. Cite the path explicitly. List the §10 decision-log questions if any.

**§10 has TWO sub-lists** (rename if user is using older template):
- **Auto-decisions taken**: defaults you picked from registry/examples, granularity choices justified by paper context. AI may take these in auto-mode without blocking.
- **Open questions for human**: items prefixed with `ASK USER:` that genuinely need a human call (e.g., paper omits a parameter, two reasonable budget tradeoffs).

Approval rules:
- **Interactive**: do not proceed to Step 5 until user signals approval ("looks good", "go ahead", "ok", or substantive revisions integrated).
- **Auto-mode**: proceed if `Open questions for human` list is empty. If any `ASK USER:` items exist, surface them and stop.

### Step 5 — Emit JSON

Generate `configs/plan_<topic>.json` from the approved design doc. Required top-level fields:

```json
{
  "_comment": "<one paragraph from design doc §0 + §1 summary>",
  "_paper_ref": "<from design doc §0 citation>",
  "_design_doc": "docs/specs/YYYY-MM-DD-<topic>-design.md",
  "_force_type_doc": "<from references/force_types.md §N>",
  "_units_doc": "<reduced or macro>",
  "campaign": [ /* one entry per run from §4 cross-product */ ],
  "pipeline": {
    "preflight": true,
    "smoke": true,
    "smoke_steps": 100,
    "production": true,
    "analyze": <bool from §5>,
    "halt_on_fail": true,
    "max_parallel": <2 default; 3-4 only if VRAM headroom>
  },
  "aggregation": { "enabled": <bool>, "outputs": [...] }
}
```

Each campaign entry must contain ONLY fields listed in `references/force_types.md` for the chosen `force_type`. Add `notes` field with one-line rationale linked to the design doc §.

### Step 6 — Validate

Run:
```
python scripts/validate_config.py configs/plan_<topic>.json --strict
```

If exit 0: proceed to Step 7.
If exit 1 or 2: read the errors and warnings, fix the JSON, re-run. Do not hand off until clean.

If a warning is intentional (e.g., super-critical ν as a control point), document it in `_comment` and downgrade strict mode in this run only by explaining to the user.

**Cross-check costs against design doc §7**: validator's `cost estimate` line should be within 2× of your design doc §7 estimate. If they differ by >2×, the validator's step-rate model is stale relative to recent runs — file an issue and trust the more recent source (usually the manifest.json of a comparable past run).

### Step 7 — Hand off

Tell the user:
- design doc path
- config path
- validation summary (exit code + estimate)
- exact launch command:
  ```
  python scripts/run_experiment.py configs/plan_<topic>.json
  ```
- expected wall time and disk

DO NOT launch the campaign yourself unless explicitly asked. The user owns the GPU-burn decision.

---

## Anti-patterns (red flags)

| Thought | Reality |
|---------|---------|
| "I'll skip the design doc — it's just one run" | The design doc IS the audit trail. Future-you needs it. |
| "I can guess the paper's φ value from context" | No. Cite or ask. |
| "Smoke wastes 30 seconds, skip it" | Smoke saves 30 minutes when something's broken. Always on. |
| "I'll fix the warnings later" | Validator must be green BEFORE handoff. |
| "Let me launch a quick test of the campaign" | User owns launch. Skill never auto-runs production. |
| "8 sweep dimensions, 64 runs, easy" | Hard cap 12 runs per plan; split if more needed. |
| "ERPotential with MT=0 is just Yukawa, reuse it." | The manifest will lie about what ran. Dead anisotropy machinery still allocated. Thesis reproductions need clean force classes — flag as §10b decision and prefer the 6-step extension over degenerate reuse. |

---

## When to extend (not just use) this skill

If you find yourself wanting to:
- Add a new field to the schema → edit `templates/plan_config.schema.json`, then `references/force_types.md`, then this skill in lockstep.
- Add a new force type → walk the user through `references/force_types.md` §3 (the 6-step extension process). Do NOT add it to the schema until the force class + tests + entry script + dispatcher update are all merged.
- Change validator rules → edit `scripts/validate_config.py`, add a regression test (validate against a known-good config and a known-bad one).

---

## Files in this skill

```
.claude/skills/paper-to-experiment/
├── SKILL.md                            # this file
├── templates/
│   ├── physics_design.md               # design doc template (12 sections)
│   └── plan_config.schema.json         # JSON Schema for configs/plan_*.json
└── references/
    ├── force_types.md                  # registry of valid force_type values
    └── examples/                       # existing approved configs as exemplars
        ├── plan_g2_er_long.json
        └── plan_d_paper_coverage.example.json
```

End of skill.
