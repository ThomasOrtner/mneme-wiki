from __future__ import annotations

from mneme_wiki import links
from mneme_wiki.packet import Chunk
from mneme_wiki.stages import autolink, extract, plan, resolve
from mneme_wiki.stages.common import Claim, KnownPage, Subject, initials, name_key, unique
from mneme_wiki.vault import Vault

from .fakes import Toy, fake_llm


def subj(name, *aliases, kind="concept", claims=("A claim.",), desc="") -> Subject:
    return Subject(name, kind, "other", list(aliases), desc or f"{name}.",
                   [Claim(c, "loc") for c in claims])  # fmt: skip


def page(path, title, *aliases, desc="", type_="concept") -> KnownPage:
    return KnownPage(path, title, type_, tuple(aliases), desc or f"{title}.")


# -- names ----------------------------------------------------------------------------
def test_name_key_and_initials() -> None:
    assert name_key("Targets") == name_key("target") == "target"
    assert name_key("PRo3D") == name_key("Pro3D")
    assert name_key("ROCC (ground)") == "rocc"
    assert name_key("Größe") == "grosse" or name_key("Größe") == "groe"
    assert initials("Regions of Interest") == {"ri", "roi"}
    assert initials("MMGIS") == set()
    assert unique(["A b", "a  B", "", "c"], exclude=["C"]) == ["A b"]


def test_shape_match() -> None:
    assert resolve.shape_match(["Strategic Planning"], ["Strategic Planning Cycle"])
    assert resolve.shape_match(["ROI"], ["Regions of Interest"])
    assert not resolve.shape_match(["DAR"], ["Rover Operations Control Centre"])
    assert not resolve.shape_match(["AB"], ["ABC"])  # under 3 chars never counts


# -- extract -------------------------------------------------------------------------
def test_parse_subjects_validates_and_clips() -> None:
    chunk = Chunk(0, "Sec", "text")
    data = {
        "subjects": [
            {"name": "  ROCC  ", "kind": "entity", "entity_kind": "org",
             "aliases": ["ROCC", "rocc", "Ops"], "description": "d", "claims": ["c1", "", 3, "c2"]},
            {"name": "", "kind": "concept", "claims": ["x"]},
            {"name": "No claims", "kind": "concept", "claims": []},
            {"name": "Weird", "kind": "thing", "claims": ["x"]},
            "junk",
        ]
    }  # fmt: skip
    subjects, dropped = extract.parse_subjects(data, chunk)
    assert [s.name for s in subjects] == ["ROCC", "Weird"] and dropped == 3
    rocc = subjects[0]
    assert rocc.entity_kind == "other" and rocc.aliases == ["Ops"]
    assert [c.text for c in rocc.claims] == ["c1", "c2"] and rocc.claims[0].locator == "Sec"
    assert subjects[1].kind == "concept"


def test_merge_within_source() -> None:
    a = subj("Target Keeper", "TK", claims=["One."])
    b = subj("TK", claims=["Two.", "One."])
    c = subj("Target", claims=["Three."])
    merged = extract.merge_within_source([a, b, c])
    assert [m.name for m in merged] == ["Target Keeper", "Target"]
    assert [x.text for x in merged[0].claims] == ["One.", "Two."]


def test_known_for_chunk_prefers_mentioned_pages() -> None:
    pages = [page(f"concepts/p{i}.md", f"Page {i}") for i in range(60)]
    pages.append(page("entities/rocc.md", "Rover Operations Control Centre", "ROCC"))
    chunk = Chunk(0, "x", "The ROCC plans. Page 7 too.")
    known = extract.known_for_chunk(chunk, pages, [subj("Earlier Thing")])
    assert set(known[:2]) == {"Rover Operations Control Centre (aka ROCC)", "Page 7"}
    assert len(known) == extract.KNOWN_LIMIT


# -- resolve -------------------------------------------------------------------------------
def test_resolve_exact_pairwise_and_in_source() -> None:
    pages = [
        page("entities/rocc.md", "Rover Operations Control Centre", "ROCC", type_="entity"),
        page("concepts/target.md", "Target", desc="A location of interest."),
        page("concepts/strategic-planning-cycle.md", "Strategic Planning Cycle"),
    ]
    toy = Toy(same=[("Strategic Planning", "Strategic Planning Cycle")])
    llm, backend = fake_llm(toy)
    subjects = [
        subj("ROCC"),  # exact alias
        subj("Planning Target", claims=["P."]),  # shape candidate "Target", model says different
        subj("Strategic Planning"),  # shape candidate, model says same
        subj("Planning Targets", claims=["Q."]),  # exact match with the new subject above
    ]
    counters: dict[str, int] = {}
    resolved, decisions = resolve.resolve(llm, subjects, pages, counters=counters)
    assert [(r.subject.name, r.target, r.how) for r in resolved] == [
        ("ROCC", "entities/rocc.md", "exact"),
        ("Planning Target", None, "new"),
        ("Strategic Planning", "concepts/strategic-planning-cycle.md", "llm"),
    ]
    assert [c.text for c in resolved[1].subject.claims] == ["P.", "Q."]
    assert decisions[3].target == "this source: Planning Target"
    check = decisions[1].checks[0]
    assert (check.candidate, check.same, check.via) == ("Target", False, "shape")
    assert counters["resolve_exact_within_source"] == 1 and counters["resolve_llm"] == 1
    assert all(r["thinking"] for r in backend.requests)  # resolve always thinks


def test_resolve_caps_candidates() -> None:
    pages = [page(f"concepts/target-{i}.md", f"Target {i}") for i in range(10)]
    llm, backend = fake_llm(Toy())
    resolve.resolve(llm, [subj("Target")], pages)
    assert len(backend.requests) == resolve.MAX_CANDIDATES


# -- plan ---------------------------------------------------------------------------------------
def test_plan_paths_and_aliases(fixture_vault) -> None:
    v = Vault(fixture_vault("windows-hostile"))
    resolved = [
        resolve.Resolved(subj("ROCC", "Ops Centre", kind="entity"), None, "new"),
        resolve.Resolved(subj("Activity Plan", "AP"), "concepts/existing.md", "exact"),
        resolve.Resolved(subj("Activity Plan", claims=()), None, "new"),
    ]
    plans = plan.plan(resolved, v)
    assert [(p.path, p.new) for p in plans] == [
        ("entities/rocc-2.md", True),  # entities/ROCC.md exists: case collision on NTFS
        ("concepts/existing.md", False),
    ]
    assert plans[0].aliases == ["Ops Centre"]
    assert plans[1].aliases == ["Activity Plan", "AP"]


# -- autolink ------------------------------------------------------------------------
NAMES = [
    autolink.Name("Activity Plan", "concepts/activity-plan.md"),
    autolink.Name("ROCC", "entities/rocc.md"),
    autolink.Name("Plan", "concepts/plan.md"),
]
INDEX = links.LinkIndex(["concepts/activity-plan.md", "entities/rocc.md", "concepts/plan.md"])


def test_autolink_rules() -> None:
    body = (
        "\n# Page\n\nThe rocc and the ROCC write an activity plan; the activity plan again.\n\n"
        "## ROCC heading\n\n| ROCC | table |\n\n> ROCC in a quote\n\n`ROCC` in code, "
        "[[entities/rocc|ROCC]] linked, [ROCC](http://x) and https://ROCC.example\n"
    )
    names = sorted(NAMES, key=lambda n: -len(n.name))
    out, added = autolink.link_body(body, "concepts/page.md", names, INDEX)
    assert added == 1  # ROCC is already linked on this page
    assert "an [[concepts/activity-plan|activity plan]]; the activity plan again" in out
    assert "The rocc and the ROCC write" in out  # short names are case-sensitive
    assert "[[concepts/plan" not in out  # "Plan" is part of the longer, linked name
    assert out.count("[[") == 2


def test_autolink_skips_self_and_ambiguous(fixture_vault) -> None:
    v = Vault(fixture_vault("clean"))
    pages = [p for _, p in v.iter_pages() if not isinstance(p, Exception)]
    names = autolink.names_for(pages)
    assert all(len(n.name) >= 3 for n in names)
    assert names == sorted(names, key=lambda n: (-len(n.name), n.name))
    body = "\n# Activity Plan\n\nThe activity plan is made by the Rover Ops Centre team.\n"
    out, added = autolink.link_body(
        body, "concepts/activity-plan.md", names, links.LinkIndex(v.files())
    )
    assert added == 1 and "[[entities/rover-operations-control-centre|Rover Ops Centre]]" in out
