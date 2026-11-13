"""#14: domain rules from WIKI.md go into the extract and resolve system prompts."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mneme_wiki import rules
from mneme_wiki.integrate import integrate
from mneme_wiki.stages import extract as extract_stage
from mneme_wiki.stages import resolve as resolve_stage
from mneme_wiki.status import overview
from mneme_wiki.vault import SCHEMA_FILE, Vault, init_vault

from .conftest import FIXTURES
from .fakes import Toy, fake_llm
from .test_vault import git_identity  # noqa: F401 - pytest fixture

PACKETS = FIXTURES / "packets"
DAY = dt.date(2026, 11, 5)
RULE = "- 'Planning Notes' sections are template structure, not subjects."


class SystemRecorder(Toy):
    """The Toy model, plus a record of every system prompt per role."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.systems: dict[str, set[str]] = {}
        self.users: dict[str, list[str]] = {}

    def __call__(self, role, system, user, schema, thinking):
        self.systems.setdefault(role, set()).add(system)
        self.users.setdefault(role, []).append(user)
        return super().__call__(role, system, user, schema, thinking)


@pytest.fixture
def vault(tmp_path: Path, git_identity) -> Vault:  # noqa: F811
    return init_vault(tmp_path / "vault", language="en", today=DAY)


def set_rules(vault: Vault, text: str) -> None:
    schema = vault.read_text(SCHEMA_FILE)
    start = schema.index("\n## Domain rules\n") + 1  # the heading, not the intro's mention
    end = schema.index("\n## ", start + 1)
    vault.write_text(SCHEMA_FILE, schema[:start] + f"## Domain rules\n\n{text}\n" + schema[end:])
    vault.git("add", "-A")
    vault.git("commit", "-q", "-m", "schema: domain rules")


def run(vault: Vault):
    toy = SystemRecorder(kinds={"ROCC": "entity", "Rover Operations Control Centre": "entity"})
    llm, _ = fake_llm(toy)
    report = integrate(vault, PACKETS / "rocc-two-ways", llm=llm,
                       inbox=vault.root.parent / "inbox", today=DAY)  # fmt: skip
    return report, toy


# -- the section --------------------------------------------------------------------------
def test_section_ends_at_the_next_heading_and_skips_code() -> None:
    text = (
        "# Wiki schema\n\n```markdown\n## Domain rules\nnot this one\n```\n\n"
        "## Domain rules\n\n- Rule one.\n<!-- a comment\n- not a rule -->\n\n\n- Rule two.\n"
        "\n## Log format\n\n- not a rule\n"
    )
    raw, line = rules.section(text)
    assert line == 8
    assert rules.clean(raw) == "- Rule one.\n\n- Rule two."
    assert rules.section("# no rules here\n") is None


def test_no_rules_leave_the_prompt_unchanged() -> None:
    assert rules.with_rules("USER", "") == "USER"
    assert rules.with_rules("USER\n", RULE) == f"USER\n\n{rules.HEADING}\n{RULE}"
    assert rules.digest("") == "" and len(rules.digest(RULE)) == 12


def test_a_new_vault_has_an_empty_rules_section(vault: Vault) -> None:
    assert "## Domain rules" in vault.read_text(SCHEMA_FILE)
    assert rules.load(vault) == ""  # the template's example is a comment


# -- integrate (fake model) -----------------------------------------------------------------
def test_without_rules_the_prompts_are_todays(vault: Vault) -> None:
    report, toy = run(vault)
    assert toy.systems["extract"] == {extract_stage.SYSTEM}
    assert toy.systems["resolve"] == {resolve_stage.SYSTEM}
    assert not any(rules.HEADING in u for us in toy.users.values() for u in us)
    assert report.rules_hash == ""


def test_rules_reach_extract_and_resolve_only(vault: Vault) -> None:
    """At the end of the user prompt, after the chunk or the pair: qwen3:14b ignored a
    rule at the end of the system prompt (9/9) and followed it there (3/3)."""
    set_rules(vault, RULE)
    report, toy = run(vault)
    for role in ("extract", "resolve"):
        assert toy.users[role] and all(
            u.endswith(f"{rules.HEADING}\n{RULE}") for u in toy.users[role]
        )
    assert toy.systems["extract"] == {extract_stage.SYSTEM}  # system prompts stay fixed
    assert not any(RULE in u for u in toy.users.get("patch", []))  # D1
    assert report.rules_hash == rules.digest(RULE)
    assert rules.digest(RULE) in vault.read_text(f"{report.run_dir}/report.md")


def test_status_reports_the_rules(vault: Vault) -> None:
    assert overview(vault)["rules"] == {"active": False, "chars": 0}
    set_rules(vault, RULE)
    assert overview(vault)["rules"] == {"active": True, "chars": len(RULE)}
