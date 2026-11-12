from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from mneme_wiki import cli
from mneme_wiki import frontmatter as fm
from mneme_wiki.integrate import IntegrateError, _strip_expansions, integrate
from mneme_wiki.lint import lint
from mneme_wiki.vault import Vault, init_vault
from mneme_wiki.workspace import Workspace

from .conftest import FIXTURES
from .fakes import Toy, fake_llm
from .test_vault import git_identity  # noqa: F401 - pytest fixture

PACKETS = FIXTURES / "packets"
DAY = dt.date(2026, 11, 5)
KINDS = {"Rover Operations Control Centre": "entity", "Science Team": "entity"}


@pytest.fixture
def vault(tmp_path: Path, git_identity) -> Vault:  # noqa: F811
    return init_vault(tmp_path / "vault", language="en", today=DAY)


def run(vault: Vault, name: str, toy: Toy | None = None, **kwargs):
    llm, backend = fake_llm(toy or Toy(kinds=KINDS))
    report = integrate(vault, PACKETS / name, llm=llm, inbox=vault.root.parent / "inbox",
                       today=DAY, **kwargs)  # fmt: skip
    return report, backend


def commits(vault: Vault) -> list[str]:
    return vault.git("log", "--format=%s").stdout.split("\n")[:-1]


def test_first_source_creates_cited_linked_pages(vault: Vault) -> None:
    report, _ = run(vault, "ops-handbook")
    assert report.ok and report.commit
    assert report.created == [
        "concepts/activity-plan.md",
        "concepts/tactical-planning-cycle.md",
        "entities/rover-operations-control-centre.md",
        "entities/science-team.md",
    ]
    assert report.source_page == "sources/rover-operations-handbook.md"
    assert commits(vault) == ["integrate: Rover Operations Handbook", "init: vault"]
    assert vault.is_clean()

    rocc = vault.read_page("entities/rover-operations-control-centre.md")
    assert rocc.meta["aliases"] == ["ROCC"] and rocc.meta["entity_kind"] == "organisation"
    assert rocc.meta["sources"] == ["[[sources/rover-operations-handbook]]"]
    assert rocc.meta["status"] == "stub"  # one claim
    assert "([[sources/rover-operations-handbook]])" in rocc.body

    src = vault.read_page(report.source_page)
    assert src.meta["origin"] == "manual:ops-handbook" and src.meta["published"] == "2026-10-01"
    assert "## Pages updated from this source" in src.body
    assert "[[entities/science-team|Science Team]]" in src.body

    plan = vault.read_text("concepts/activity-plan.md")  # autolinked mention
    assert "[[entities/rover-operations-control-centre|Rover Operations Control Centre]]" in plan
    assert "integrate | Rover Operations Handbook" in vault.read_text("log.md")
    assert "[[concepts/activity-plan|Activity Plan]]" in vault.read_text("index.md")
    findings = lint(vault)
    assert findings.ok and not [f for f in findings.findings if f.check != "orphan"]


def test_second_source_updates_existing_pages(vault: Vault) -> None:
    run(vault, "ops-handbook")
    toy = Toy(kinds=KINDS, same=[("Tactical Planning", "Tactical Planning Cycle")])
    report, backend = run(vault, "planning-notes", toy)
    assert report.ok and report.resolve["exact"] == 1 and report.resolve["model"] == 1
    assert report.updated == [
        "concepts/tactical-planning-cycle.md",
        "entities/rover-operations-control-centre.md",
    ]
    assert report.created == ["concepts/planning-target.md"]
    assert not any(r["role"] == "summary" for r in backend.requests)  # summary.md was used

    tpc = vault.read_page("concepts/tactical-planning-cycle.md")
    assert tpc.meta["sources"] == [
        "[[sources/rover-operations-handbook]]",
        "[[sources/planning-workshop-notes]]",
    ]
    assert tpc.meta["aliases"] == ["Tactical Planning"]
    assert (
        "takes about 24 hours" in tpc.body and "([[sources/planning-workshop-notes]])" in tpc.body
    )
    src = vault.read_text("sources/planning-workshop-notes.md")
    assert "Notes from the weekly planning workshop: who runs it" in src  # upstream summary
    assert "- [[concepts/tactical-planning-cycle|Tactical Planning Cycle]]" in src  # both ways
    assert len(commits(vault)) == 3 and lint(vault).ok

    with pytest.raises(IntegrateError, match="already integrated"):
        run(vault, "planning-notes", toy)


def test_dry_run_and_stage_write_nothing(vault: Vault) -> None:
    head = commits(vault)
    report, _ = run(vault, "ops-handbook", dry_run=True)
    assert report.dry_run and not report.commit and report.created
    assert "+++ b/entities/science-team.md" in report.diff
    assert commits(vault) == head and vault.is_clean()
    assert not vault.exists("entities/science-team.md")
    runs = list((vault.root / ".mneme-wiki/runs").iterdir())
    assert {"report.md", "diff.patch", "calls.jsonl", "resolve_log.jsonl"} <= {
        p.name for p in runs[0].iterdir()
    }

    report, backend = run(vault, "ops-handbook", stop_after="extract")
    assert report.stopped_after == "extract"
    assert {s["name"] for s in report.stage_output} >= {"Science Team", "Activity Plan"}
    assert {r["role"] for r in backend.requests} == {"extract"}


def test_dirty_vault_is_refused(vault: Vault) -> None:
    (vault.root / "concepts/human.md").write_text("draft", encoding="utf-8")
    with pytest.raises(IntegrateError, match="uncommitted changes"):
        run(vault, "ops-handbook")
    run(vault, "ops-handbook", dry_run=True)  # a dry run is fine


def test_rejected_edits_go_to_the_inbox(vault: Vault) -> None:
    run(vault, "ops-handbook")

    def shrink(user: str, n: int):
        if "CURRENT PAGE (concepts/tactical-planning-cycle)" in user:
            return {"lead": "", "ops": [{"section": "Overview", "op": "replace", "text": "x"}]}
        return None

    toy = Toy(kinds=KINDS, same=[("Tactical Planning", "Tactical Planning Cycle")],
              patch_answer=shrink)  # fmt: skip
    before = vault.read_text("concepts/tactical-planning-cycle.md")
    report, backend = run(vault, "planning-notes", toy)
    assert report.ok
    tpc = [r for r in report.rejected if r["page"] == "concepts/tactical-planning-cycle.md"]
    assert len(tpc) == 1 and "drops links" in tpc[0]["reason"]
    patch_prompts = [r["user"] for r in backend.requests if r["role"] == "patch"]
    assert any("Your previous answer was partly rejected" in p for p in patch_prompts)  # retried
    after = vault.read_page("concepts/tactical-planning-cycle.md")
    assert fm.parse(before).body.strip() in after.body  # old content intact
    saved = list(Path(report.rejected_dir).glob("*.json"))
    assert [p.name for p in saved] == ["concepts-tactical-planning-cycle.json"]
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["proposal"]["ops"][0]["op"] == "replace"


def test_failed_patch_still_creates_new_page_skeleton(vault: Vault) -> None:
    toy = Toy(kinds=KINDS, patch_answer=lambda user, n: "{not json")
    report, _ = run(vault, "ops-handbook", toy)
    assert report.ok and len(report.created) == 4
    assert all(r["reason"] == "no valid answer from the model" for r in report.rejected)
    page = vault.read_page("entities/science-team.md")
    assert "Science Team as described in the source. ([[sources/" in page.body
    assert lint(vault).ok


class Inventing(Toy):
    """Spells out abbreviations the way local models do, in the summary and in patches."""

    def summary(self, user: str) -> dict:
        return {
            "summary": "The ROCC (Rover Orbit Command Centre) uses the Data Archive and "
            "Retrieval (DAR).",
            "key_points": ["One."],
        }

    def patch(self, user: str) -> dict:
        answer = super().patch(user)
        for op in answer["ops"]:
            op["text"] = op["text"].replace("- ", "- The DAR (Data Archive Room) helps. ", 1)
        return answer


def test_invented_expansions_never_reach_the_vault(vault: Vault) -> None:
    report, _ = run(vault, "ops-handbook", Inventing(kinds=KINDS))
    assert report.counters["expansion_removed"] >= 3
    pages = "\n".join(vault.read_text(rel) for rel in vault.files() if rel.endswith(".md"))
    for invented in (
        "Rover Orbit Command Centre",
        "Data Archive and Retrieval",
        "Data Archive Room",
    ):
        assert invented not in pages
    assert "uses the DAR" in pages and "The DAR helps." in pages


class NameInventing(Toy):
    """Glues an invented expansion onto an acronym, as qwen3:14b did (#25)."""

    def extract(self, user: str) -> dict:
        answer = super().extract(user)
        for s in answer["subjects"]:
            if s["name"] == "UPC":
                s["name"] = "UPCUplink Processing Centre"
                s["aliases"] = ["UPC", "Uplink Processing Centre"]
                s["description"] = "The UPC (Uplink Processing Centre) receives command products."
        return answer


def test_invented_title_and_alias_never_reach_the_vault(vault: Vault) -> None:
    report, _ = run(vault, "uplink-handover", NameInventing(kinds={**KINDS, "UPC": "entity"}))
    assert report.ok
    assert "entities/upc.md" in report.created
    assert not any("uplink-processing" in rel for rel in vault.files())
    page = vault.read_page("entities/upc.md")
    assert page.title == "UPC"
    assert "Uplink Processing Centre" not in vault.read_text("entities/upc.md")
    assert "The UPC receives command products." in page.body
    assert report.counters["title_unbacked_replaced"] == 1
    assert report.counters["alias_unbacked_dropped"] == 1
    # a title the source spells out stays, with its acronym as alias
    rocc = vault.read_page("entities/rover-operations-control-centre.md")
    assert rocc.title == "Rover Operations Control Centre" and rocc.meta["aliases"] == ["ROCC"]


def test_a_new_pages_own_names_are_no_expansion_evidence(vault: Vault) -> None:
    ws = Workspace(vault)
    rel = "entities/uplink-processing-centre.md"
    ws.write_text(rel, "---\ntitle: Uplink Processing Centre\ntype: entity\naliases: [UPC]\n"
                       "---\n# Uplink Processing Centre\n\nThe UPC (Uplink Processing Centre) "
                       "receives commands.\n")  # fmt: skip
    counters: dict[str, int] = {}
    _strip_expansions(ws, vault, [rel], "The ROCC sends commands to UPC.", counters)
    assert "The UPC receives commands." in ws.read_text(rel)
    assert counters["expansion_removed"] == 1


def test_expansions_already_in_the_vault_stay(vault: Vault) -> None:
    run(vault, "ops-handbook")
    rel = "entities/rover-operations-control-centre.md"  # the second source updates it
    page = vault.read_page(rel)
    page.body += "\nThe ROCC (Rover Orbit Command Centre) is a human note.\n"
    vault.write_page(page)
    vault.git("add", "-A")
    vault.git("commit", "-m", "human edit")
    report, _ = run(vault, "planning-notes", Inventing(kinds=KINDS))
    assert rel in report.updated
    assert "(Rover Orbit Command Centre) is a human note" in vault.read_text(rel)


def test_cli_integrate_json_and_stage(vault: Vault, capsys, monkeypatch) -> None:
    llm, _ = fake_llm(Toy(kinds=KINDS))
    monkeypatch.setattr("mneme_wiki.integrate.LLM", lambda **kw: llm)
    out = vault.root.parent / "plan.json"
    args = ["integrate", str(PACKETS / "ops-handbook"), "--vault", str(vault.root)]
    assert cli.main([*args, "--stage", "plan", "--out", str(out), "--json"]) == 0
    capsys.readouterr()
    plans = json.loads(out.read_text(encoding="utf-8"))
    assert {p["path"] for p in plans} >= {"entities/science-team.md"}
    assert cli.main([*args, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["runs"][0]["commit"] and "diff" not in data["runs"][0]
    assert cli.main([*args, "--json"]) == 2  # already integrated
    assert "already integrated" in json.loads(capsys.readouterr().out)["error"]
    assert cli.main(["integrate", "no-such-packet", "--vault", str(vault.root)]) == 2
