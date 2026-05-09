"""Regression: every `{{X}}` placeholder in creator's scaffold templates
must be documented in either the SKILL.md substitution table or the
interview.md profile. Catches drift when scaffold templates evolve.

Run: pytest tests/test_creator_scaffold.py -v
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREATOR = ROOT / ".claude" / "skills" / "creator"
SCAFFOLD = CREATOR / "templates" / "skill_scaffold"
SKILL_MD = CREATOR / "SKILL.md"
INTERVIEW = CREATOR / "templates" / "interview.md"
DISTILL = CREATOR / "references" / "distillation.md"

# Tokens that legitimately appear in templates without needing substitution
# (placeholders for the user to fill, not for `creator` to substitute).
USER_PLACEHOLDERS = {"<your project>", "<...>"}


def _all_placeholders(path: Path) -> set[str]:
    """Return every `{{X}}` token from one file."""
    return set(re.findall(r"\{\{([A-Z0-9_<>]+)\}\}", path.read_text(encoding="utf-8")))


def test_scaffold_dir_exists():
    assert SCAFFOLD.is_dir(), f"missing {SCAFFOLD}"


def test_required_scaffold_files():
    expected = {
        "SKILL.md.tmpl",
        "design.md.tmpl",
        "schema.json.tmpl",
        "registry.md.tmpl",
        "validator.py.tmpl",
    }
    actual = {p.name for p in SCAFFOLD.iterdir() if p.is_file()}
    missing = expected - actual
    assert not missing, f"scaffold missing: {missing}"


def test_every_placeholder_documented_in_skill_md():
    """Every `{{X}}` in any .tmpl must be mentioned in creator/SKILL.md or
    creator/templates/interview.md so that creator knows where to source it."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    interview_text = INTERVIEW.read_text(encoding="utf-8")
    distill_text = DISTILL.read_text(encoding="utf-8")
    docs = skill_text + "\n" + interview_text + "\n" + distill_text

    all_tokens = set()
    for tmpl in SCAFFOLD.glob("*.tmpl"):
        all_tokens.update(_all_placeholders(tmpl))

    # ignore <stuff> inside {{...}} which are themselves placeholder placeholders
    real_tokens = {t for t in all_tokens if "<" not in t}

    undocumented = []
    for token in sorted(real_tokens):
        # The token name should appear somewhere in skill / interview / distillation docs.
        if f"{{{{{token}}}}}" not in docs and token not in docs:
            undocumented.append(token)

    assert not undocumented, (
        f"creator scaffold uses placeholders not documented anywhere "
        f"(neither in SKILL.md substitution table, nor interview.md, "
        f"nor distillation.md):\n  " + "\n  ".join(undocumented)
    )


def test_skill_md_references_each_scaffold_file():
    """SKILL.md `## Files` section should mention each .tmpl by name so that
    a fresh user reading the skill knows what gets generated."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    for tmpl in SCAFFOLD.glob("*.tmpl"):
        # The basename (without .tmpl) should appear in SKILL.md
        stem = tmpl.name.replace(".tmpl", "")
        assert stem in skill_text, f"SKILL.md doesn't mention scaffold file '{stem}'"


def test_no_md_test1_specific_strings_leaked_into_scaffold():
    """Scaffold should NOT mention md-for-dummies-specific names (PRX, ER,
    Hertzian, etc.). If it does, distillation has a leak."""
    forbidden = ["PRX", "Hertzian", "Ivlev", "Taichi", "MD_test1", "md-for-dummies",
                 "ERPotential", "T0_star", "phi_target"]
    leaks = []
    for tmpl in SCAFFOLD.glob("*.tmpl"):
        text = tmpl.read_text(encoding="utf-8")
        for word in forbidden:
            if word in text:
                leaks.append(f"{tmpl.name}: contains '{word}'")
    assert not leaks, "scaffold leaks framework-specific names:\n  " + "\n  ".join(leaks)
