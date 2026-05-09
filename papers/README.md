# Papers folder

Reference PDFs that the `paper-to-experiment` skill consumes during a reproduction task.

## Naming convention

`<first_author>_<journal><year>.pdf` — lowercase, underscore-separated.

Examples:
- `pedersen_prl2018.pdf` → Pedersen et al., *Phys. Rev. Lett.* **120**, 165501 (2018)
- `bernard_prl2011.pdf` → Bernard & Krauth, *Phys. Rev. Lett.* **107**, 155704 (2011)

The skill's `templates/physics_design.md §0 metadata` field `paper_pdf` must point to a relative path under this folder. If the PDF isn't here, the skill's Step 2 stops with a clear error — abstract-only reproduction is **not** supported.

## Cross-reference

`CANDIDATES.md` — survey of open-access classical-MD-friendly papers vetted by an automated search agent on 2026-05-09. Use as a starting list when picking a new reproduction target.

## Adding a new paper

1. Drop the PDF in this folder using the naming convention above.
2. Verify it's a real PDF (`file <name>.pdf` should report `PDF document`).
3. Reference it in `templates/physics_design.md §0 paper_pdf` in any new design doc.
