from __future__ import annotations

from mneme_wiki import links
from mneme_wiki.packet import Chunk
from mneme_wiki.stages import autolink, extract, names, plan, resolve
from mneme_wiki.stages.common import (
    Claim,
    KnownPage,
    Subject,
    initials,
    looks_local_id,
    name_key,
    unique,
)
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


def test_looks_local_id() -> None:
    # #13 D1: short, uppercase letters + digits = may be local to one document
    for name in ["WP2", "D3", "MS3", "AP4", "WP 2", "T2.1", "D1.2a"]:
        assert looks_local_id(name), name
    for name in ["ROCC", "PRo3D", "3D", "Probe Alpha WP2", "COVID19", "Task", "H2O", ""]:
        assert not looks_local_id(name), name


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
    b = subj("Target Keepers", "Keeper", claims=["Two.", "One."])
    c = subj("Target", claims=["Three."])
    merged = extract.merge_within_source([a, b, c])
    assert [m.name for m in merged] == ["Target Keeper", "Target"]
    assert [x.text for x in merged[0].claims] == ["One.", "Two."]
    assert merged[0].aliases == ["TK", "Keeper"]  # "Target Keepers" is the name itself


def test_merge_within_source_never_unions_through_an_alias() -> None:
    # #15: a related name listed as an alias must not fold two subjects without a check
    mission = subj("Probe Alpha", "PA", "Rover A", claims=["Mission."])
    rover = subj("Rover A", claims=["Rover."])
    tk = subj("TK", claims=["Two."])
    keeper = subj("Target Keeper", "TK", claims=["One."])
    merged = extract.merge_within_source([mission, rover, tk, keeper])
    assert [m.name for m in merged] == ["Probe Alpha", "Rover A", "TK", "Target Keeper"]


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


def test_resolve_alias_match_is_checked_not_exact() -> None:
    # #15: the subject's alias "Cam B" names an existing page; that is no exact match
    pages = [page("entities/cam-b.md", "Cam B", desc="A camera of another mission.",
                  type_="entity")]  # fmt: skip
    llm, backend = fake_llm(Toy())  # the model says "different"
    mission = subj("Probe Alpha", "PA", "Rover A", "Cam A", "Cam B", kind="entity")
    counters: dict[str, int] = {}
    resolved, decisions = resolve.resolve(llm, [mission], pages, counters=counters)
    assert [(r.subject.name, r.target, r.how) for r in resolved] == [("Probe Alpha", None, "new")]
    assert decisions[0].how == "new" and decisions[0].checks[0].candidate == "Cam B"
    assert decisions[0].checks[0].via == "alias"
    assert len(backend.requests) == 1  # one yes/no question, then "new"
    # the alias that is another page's title is dropped and counted
    assert resolved[0].subject.aliases == ["PA", "Rover A", "Cam A"]
    assert counters["alias_conflict_dropped"] == 1


def test_resolve_alias_match_merges_when_the_model_says_same() -> None:
    pages = [page("entities/rocc.md", "Rover Operations Control Centre", "ROCC", type_="entity")]
    llm, _ = fake_llm(Toy(same=[("Ops Centre", "Rover Operations Control Centre")]))
    resolved, decisions = resolve.resolve(llm, [subj("Ops Centre", "ROCC")], pages)
    assert [(r.target, r.how) for r in resolved] == [("entities/rocc.md", "llm")]
    assert decisions[0].checks[0].via == "alias"
    assert resolved[0].subject.aliases == ["ROCC"]  # its own page's alias is kept


def test_resolve_within_source_alias_is_checked_not_folded() -> None:
    # #15: a subject whose alias is another subject's name is not folded without a check
    llm, backend = fake_llm(Toy())
    mission = subj("Probe Alpha", "Rover A", kind="entity", claims=["Mission."])
    rover = subj("Rover A", kind="entity", claims=["Rover."])
    counters: dict[str, int] = {}
    resolved, decisions = resolve.resolve(llm, [mission, rover], [], counters=counters)
    assert [(r.subject.name, r.target, r.how) for r in resolved] == [
        ("Probe Alpha", None, "new"),
        ("Rover A", None, "new"),
    ]
    assert decisions[1].checks[0].candidate == "Probe Alpha"
    assert decisions[1].checks[0].via == "alias"
    # the mission's alias is now another new page's name: dropped
    assert resolved[0].subject.aliases == []
    assert counters["alias_conflict_dropped"] == 1


def test_resolve_within_source_alias_folds_when_the_model_says_same() -> None:
    llm, _ = fake_llm(Toy(same=[("ROCC", "Rover Operations Control Centre")]))
    full = subj("Rover Operations Control Centre", "ROCC", kind="entity", claims=["A."])
    short = subj("ROCC", kind="entity", claims=["B."])
    resolved, decisions = resolve.resolve(llm, [full, short], [])
    assert len(resolved) == 1 and [c.text for c in resolved[0].subject.claims] == ["A.", "B."]
    assert decisions[1].how == "llm"
    assert decisions[1].target == "this source: Rover Operations Control Centre"


def test_resolve_local_id_from_another_source_is_checked_not_exact() -> None:
    # #13: a bare "WP2" of source B never exact-matches the "WP2" page of source A
    pages = [page("entities/wp2.md", "WP2", desc="Data Processing work package of Alpha.")]
    llm, backend = fake_llm(Toy())  # the model says "different"
    wp2 = subj("WP2", desc="Requirements Consolidation work package of Beta.")
    resolved, decisions = resolve.resolve(llm, [wp2], pages)
    assert [(r.target, r.how) for r in resolved] == [(None, "new")]
    assert decisions[0].checks[0].candidate == "WP2"
    assert decisions[0].checks[0].via == "local-id"
    assert len(backend.requests) == 1


def test_resolve_local_id_merges_when_the_model_says_same() -> None:
    pages = [page("entities/wp2.md", "WP2", "Alpha WP2")]
    llm, _ = fake_llm(Toy(same=[("WP2", "WP2")]))
    resolved, _ = resolve.resolve(llm, [subj("WP2")], pages)
    assert [(r.target, r.how) for r in resolved] == [("entities/wp2.md", "llm")]


def test_resolve_local_id_within_source_is_still_exact() -> None:
    # inside one document a local id names one thing: no model call
    llm, backend = fake_llm(Toy())
    first, again = subj("WP2", claims=["A."]), subj("WP2", claims=["B."])
    resolved, decisions = resolve.resolve(llm, [first, again], [])
    assert len(resolved) == 1 and decisions[1].how == "exact"
    assert backend.requests == []


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


def test_plan_qualifies_local_id_aliases(fixture_vault) -> None:
    # #13 D3: a local id is never a bare alias; with an owner short name it becomes PA-WP2
    v = Vault(fixture_vault("clean"))
    resolved = [
        resolve.Resolved(subj("Project Alpha", "PA", kind="entity"), None, "new"),
        resolve.Resolved(subj("Project Alpha WP2", "WP2", kind="entity"), None, "new"),
        resolve.Resolved(subj("Project Alpha D3: Viewer", "D3", kind="entity"), None, "new"),
        resolve.Resolved(subj("Project Beta WP2", "WP2", "Beta WP", kind="entity"), None, "new"),
        # no owner in front of the id in the title: no evidence it is local, alias kept
        resolve.Resolved(subj("Probe 2031", "P31", kind="entity"), None, "new"),
    ]
    counters: dict[str, int] = {}
    plans = plan.plan(resolved, v, counters=counters)
    aliases = {p.title: p.aliases for p in plans}
    assert aliases["Project Alpha WP2"] == ["PA-WP2"]
    assert aliases["Project Alpha D3: Viewer"] == ["PA-D3"]
    assert aliases["Project Beta WP2"] == ["Beta WP"]  # no short name for Beta: dropped
    assert aliases["Probe 2031"] == ["P31"]
    assert counters == {"local_id_alias_dropped": 3, "local_id_alias_qualified": 2}


def test_plan_qualifies_a_colliding_local_id_title_with_the_source(fixture_vault) -> None:
    # #13: extract may leave "D1" bare in two proposals; resolve keeps them apart, and the
    # second page gets the source title in front instead of a duplicate title "D1"
    root = fixture_vault("clean")
    (root / "entities" / "d1.md").write_text(
        "---\ntitle: D1\ntype: entity\nentity_kind: document\n---\n\n# D1\n\nA.\n",
        encoding="utf-8",
    )
    v = Vault(root)
    resolved = [resolve.Resolved(subj("D1", kind="entity"), None, "new")]
    counters: dict[str, int] = {}
    plans = plan.plan(resolved, v, owner="Project Beta Proposal", counters=counters)
    assert (plans[0].path, plans[0].title) == (
        "entities/project-beta-proposal-d1.md",
        "Project Beta Proposal D1",
    )
    assert plans[0].aliases == []  # bare "D1" dropped, the owner has no short name
    assert counters["local_id_title_qualified"] == 1


def test_plan_keeps_a_local_id_shaped_title_without_a_collision(fixture_vault) -> None:
    # "M20"-style names can be global (a mission acronym): renamed only on a collision
    v = Vault(fixture_vault("clean"))
    resolved = [resolve.Resolved(subj("P31", kind="entity"), None, "new")]
    counters: dict[str, int] = {}
    plans = plan.plan(resolved, v, owner="Probe Overview", counters=counters)
    assert (plans[0].path, plans[0].title) == ("entities/p31.md", "P31")
    assert counters == {}


def test_plan_takes_owner_short_name_from_an_existing_page(fixture_vault) -> None:
    v = Vault(fixture_vault("clean"))
    resolved = [
        resolve.Resolved(subj("Rover Operations Control Centre T2.1", "T2.1"), None, "new"),
    ]
    plans = plan.plan(resolved, v)
    assert plans[0].aliases == ["ROCC-T2.1"]


# -- autolink ------------------------------------------------------------------------
NAMES = [
    autolink.Name("Activity Plan", "concepts/activity-plan.md"),
    autolink.Name("ROCC", "entities/rocc.md"),
    autolink.Name("Plan", "concepts/plan.md"),
]
INDEX = links.LinkIndex(["concepts/activity-plan.md", "entities/rocc.md", "concepts/plan.md"])


# -- names (#25) --------------------------------------------------------------------------
def test_names_normalise_case_hyphens_and_plurals() -> None:
    ev = names.Evidence("Two Activity-Plans per sol; the ROCC's team.", [])
    assert ev.backs("Activity Plan") and ev.backs("activity plans") and ev.backs("ROCC")
    assert not ev.backs("Plan Activity")  # reordered
    assert not ev.backs("ActivityPlan")  # glued
    assert not ev.backs("")


def test_names_owner_in_front_of_a_backed_name_is_backed() -> None:
    """D3 as amended: extract qualifies local ids with their owner (TD-32)."""
    text = "Project Alpha builds a viewer. WP2 turns images into mosaics. A steering board meets."
    ev = names.Evidence(text, [], "Project Alpha Proposal")
    assert ev.backs("Project Alpha WP2")  # owner from the source title
    assert ev.backs("Project Alpha Steering Board")
    assert not ev.backs("Mosaics WP2")  # "mosaics" is a word of the source, not a name
    assert not ev.backs("Project Alpha Deliverable D2")  # "Deliverable D2" isn't in the text
    ev = names.Evidence("The ROCC delivers to UPC.", [page("e/rocc.md", "ROCC")])
    assert ev.backs("ROCC UPC")  # owner = an existing page's name
    assert not ev.backs("UPC Uplink Processing Centre")  # the expansion itself is invented


def test_names_a_subject_of_this_source_can_own_another() -> None:
    ev = names.Evidence("Team Rho runs the lab. WP2 makes mosaics.", [])
    owner = resolve.Resolved(subj("Team Rho"), None, "new")
    wp = resolve.Resolved(subj("Team Rho WP2"), None, "new")
    kept, changes = names.check([wp, owner], [], ev)
    assert [r.subject.name for r in kept] == ["Team Rho WP2", "Team Rho"] and not changes


def test_names_keep_backed_title_and_replace_an_invented_one() -> None:
    ev = names.Evidence("The ROCC delivers the command products to UPC for uplink.", [])
    r = resolve.Resolved(subj("UPCUplink Processing Centre", "UPC", "Uplink Processing Centre"),
                         None, "new")  # fmt: skip
    counters: dict[str, int] = {}
    kept, changes = names.check([r], [], ev, counters=counters)
    assert kept[0].subject.name == "UPC" and kept[0].subject.aliases == []
    assert counters == {"alias_unbacked_dropped": 1, "title_unbacked_replaced": 1}
    assert [c.change for c in changes] == ["alias_dropped", "title_replaced"]


def test_names_existing_page_names_are_evidence() -> None:
    known = [page("entities/rocc.md", "Rover Operations Control Centre", "ROCC")]
    ev = names.Evidence("The ROCC plans the sol.", known)
    r = resolve.Resolved(subj("Rover Operations Control Centre", "ROCC"), None, "new")
    kept, changes = names.check([r], known, ev)
    assert kept[0].subject.name == "Rover Operations Control Centre" and not changes


def test_names_unbacked_name_of_a_matched_subject_is_not_added_to_the_page() -> None:
    known = [page("entities/rocc.md", "Rover Operations Control Centre", "ROCC")]
    ev = names.Evidence("The ROCC plans the sol.", known)
    r = resolve.Resolved(subj("Rover Orbit Command Centre"), "entities/rocc.md", "llm")
    kept, _ = names.check([r], known, ev)
    assert kept[0].subject.name == "Rover Operations Control Centre"


def test_names_fallback_local_id_is_qualified_with_the_project() -> None:
    """#27: "Deliverable D2" isn't in the text, "D2" is; with a project the page is
    "Project Alpha D2", so the project's later reports find it by exact match."""
    ev = names.Evidence("WP2 delivers D2, the mosaic pipeline.", [], "", ["Project Alpha"])
    r = resolve.Resolved(subj("Project Alpha Deliverable D2", "D2"), None, "new")
    kept, _ = names.check([r], [], ev, project="Project Alpha")
    assert kept[0].subject.name == "Project Alpha D2"
    r = resolve.Resolved(subj("Project Alpha Deliverable D2", "D2"), None, "new")
    kept, _ = names.check([r], [], ev)  # without a project: as before
    assert kept[0].subject.name == "D2"


def test_names_subject_named_like_the_source_is_skipped() -> None:
    ev = names.Evidence("The Project Alpha Proposal describes three work packages.", [])
    doc = resolve.Resolved(subj("Project Alpha Proposal"), None, "new")
    wp = resolve.Resolved(subj("Work Package"), None, "new")
    counters: dict[str, int] = {}
    kept, _ = names.check([doc, wp], [], ev, counters=counters,
                          source_title="Project Alpha Proposal")  # fmt: skip
    assert [r.subject.name for r in kept] == ["Work Package"]
    assert counters["subject_is_source_skipped"] == 1


def test_names_subject_without_a_backed_name_is_skipped() -> None:
    ev = names.Evidence("Nothing relevant here.", [])
    r = resolve.Resolved(subj("Data Archive Room", "Data Archive and Retrieval"), None, "new")
    counters: dict[str, int] = {}
    kept, changes = names.check([r], [], ev, counters=counters)
    assert kept == [] and changes[-1].change == "subject_skipped"
    assert counters["subject_unbacked_skipped"] == 1


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
