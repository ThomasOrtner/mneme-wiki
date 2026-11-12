from __future__ import annotations

from mneme_wiki import edits, links

SRC = "sources/handbook"
FILES = [
    "sources/handbook.md",
    "sources/other.md",
    "entities/rocc.md",
    "concepts/activity-plan.md",
    "concepts/target.md",
]
CTX = edits.Context(SRC, links.LinkIndex(FILES))

BODY = """
# ROCC

The ROCC operates the rover ([[sources/other]]).

## Planning

- It runs the [[concepts/activity-plan|activity plan]] every sol ([[sources/other]]).

## History

Hand-written notes, kept   exactly   as they are.
"""


def prop(*ops, lead: str = "") -> edits.Proposal:
    return edits.Proposal(lead, [edits.Op(*op) for op in ops])


def test_split_render_is_identity() -> None:
    for body in (BODY, "", "no headings\n", "\n# T\n\n```\n## not a section\n```\n## S\nx"):
        assert edits.split(body).render() == body
    parts = edits.split(BODY)
    assert [s.name for s in parts.sections] == ["Planning", "History"]


def test_append_keeps_other_sections_byte_identical() -> None:
    r = edits.apply(
        BODY, prop(("Planning", "append", "- Plans are made daily for the rover.")), CTX
    )
    assert r.changed and not r.rejected
    assert "Hand-written notes, kept   exactly   as they are.\n" in r.body
    planning = r.body.split("## Planning")[1].split("## History")[0]
    assert planning == (
        "\n\n- It runs the [[concepts/activity-plan|activity plan]] every sol "
        "([[sources/other]]).\n"
        "- Plans are made daily for the rover. ([[sources/handbook]])\n\n"
    )
    assert r.counters["missing_citation_added"] == 1


def test_new_section_at_end_and_section_names_are_case_insensitive() -> None:
    r = edits.apply(
        BODY,
        prop(
            ("## planning", "append", "- A second fact about planning cycles here."),
            ("Open questions", "append", "Is the plan ever late for the rover team?"),
        ),
        CTX,
    )
    assert r.body.count("## Planning") == 1 and "## planning" not in r.body
    assert r.body.endswith(
        "## Open questions\n\nIs the plan ever late for the rover team? ([[sources/handbook]])\n"
    )


def test_replace_that_drops_a_link_is_rejected() -> None:
    r = edits.apply(
        BODY, prop(("Planning", "replace", "- It plans every sol, a long sentence.")), CTX
    )
    assert not r.changed
    assert r.rejected and "drops links" in r.rejected[0].reason and r.rejected[0].retry
    assert r.counters["replace_rejected_lost_links"] == 1


def test_replace_that_shrinks_is_rejected_and_a_good_one_applies() -> None:
    long = "\n".join(
        f"- Fact {i} about the [[concepts/activity-plan]] ([[{SRC}]])." for i in range(6)
    )
    body = f"\n# X\n\n## S\n\n{long}\n"
    short = f"- [[concepts/activity-plan]] ([[{SRC}]])"
    r = edits.apply(body, prop(("S", "replace", short)), CTX)
    assert not r.changed and "shrinks" in r.rejected[0].reason
    better = long.replace("Fact", "Statement")
    r = edits.apply(body, prop(("S", "replace", better)), CTX)
    assert r.changed and r.counters["op_replace"] == 1 and "Statement 5" in r.body


def test_unknown_links_are_unwrapped() -> None:
    text = "- Uses [[concepts/missing|the missing thing]] and [[nowhere]] and [[target]]."
    r = edits.apply(BODY, prop(("New", "append", text)), CTX)
    assert "the missing thing and nowhere and [[target]]" in r.body
    assert r.counters["invalid_link_removed"] == 2


def test_escaped_newlines_and_echoed_headings() -> None:
    text = "## Planning\\n- One fact about rover planning here.\\n- Two facts about rover planning."
    r = edits.apply(BODY, prop(("Planning", "append", text)), CTX)
    assert r.counters["escaped_newlines_fixed"] == 1
    assert r.counters["echoed_heading_dropped"] == 1
    assert r.body.count("## Planning") == 1
    text = "- Fact one about the rover operations.\n## Sub topic\n- Fact two about the rover team."
    r = edits.apply(BODY, prop(("Planning", "append", text)), CTX)
    assert "### Sub topic" in r.body and len(edits.split(r.body).sections) == 2


def test_duplicate_lines_are_not_added() -> None:
    text = (
        "- It runs the [[concepts/activity-plan|activity plan]] every sol ([[sources/handbook]])."
    )
    r = edits.apply(BODY, prop(("Planning", "append", text)), CTX)
    assert not r.changed and r.counters["duplicate_line_skipped"] == 1


def test_lead_change_and_lead_that_loses_links() -> None:
    body = "\n# ROCC\n\nThe ROCC runs the [[concepts/activity-plan]] ([[sources/other]]).\n"
    r = edits.apply(body, prop(lead="The ROCC operates the rover from the ground."), CTX)
    assert not r.changed and r.counters["lead_lost_links_kept_old"] == 1
    new_lead = "The ROCC runs the [[concepts/activity-plan]] from Turin ([[sources/other]])."
    r = edits.apply(body, prop(lead=new_lead), CTX)
    assert r.changed and r.body == f"\n# ROCC\n\n{new_lead}\n"


def test_lead_added_when_missing_gets_a_citation() -> None:
    r = edits.apply("\n# T\n", prop(lead="A thing that the rover team uses daily."), CTX)
    assert r.body == "\n# T\n\nA thing that the rover team uses daily. ([[sources/handbook]])\n"


def test_short_and_structural_lines_are_not_cited() -> None:
    text = (
        "| a | b |\n> quote about the rover team here\n- See also\n"
        "```\ncode line with many words\n```"
    )
    r = edits.apply("\n# T\n", prop(("S", "append", text)), CTX)
    assert "([[sources/handbook]])" not in r.body


def test_crlf_body_and_oversized_op() -> None:
    crlf = BODY.replace("\n", "\r\n")
    r = edits.apply(crlf, prop(("History", "append", "More notes about the rover history.")), CTX)
    assert r.changed and "\r" not in r.body  # frontmatter.dump restores CRLF on write
    r = edits.apply(BODY, prop(("S", "append", "x" * (edits.MAX_OP_CHARS + 1))), CTX)
    assert not r.changed and "longer than" in r.rejected[0].reason


def test_proposal_from_messy_json() -> None:
    p = edits.Proposal.from_json(
        {"lead": None, "ops": [{"section": "A", "op": "delete", "text": "t"}, {"x": 1}, "junk"]}
    )
    assert p.lead == "" and [(o.section, o.op) for o in p.ops] == [("A", "append")]


# #22: lines that speak for another source (or for nobody) are never rewritten
SCHEDULE = """
# Project Alpha

Project Alpha is a research project ([[sources/proposal-a]]).

## Schedule

- The project runs from 2024 to 2026 ([[sources/proposal-a]]).
- Kick-off meeting held in Vienna with all partners ([[sources/proposal-b]]).
Hand-written note: check the   timeline with the partners.
"""
CTX_B = edits.Context(
    "sources/proposal-b",
    links.LinkIndex(["sources/proposal-a.md", "sources/proposal-b.md", "concepts/x.md"]),
)


def test_replace_that_rewrites_another_sources_line_is_rejected() -> None:
    new = (
        "- The project runs from 2025 to 2027 ([[sources/proposal-a]]).\n"
        "- Kick-off meeting held in Vienna with all partners ([[sources/proposal-b]]).\n"
        "Hand-written note: check the   timeline with the partners."
    )
    r = edits.apply(SCHEDULE, prop(("Schedule", "replace", new)), CTX_B)
    assert not r.changed and r.body == SCHEDULE
    (rej,) = r.rejected
    assert rej.retry and rej.section == "Schedule"
    assert "2024 to 2026" in rej.reason and "use append" in rej.reason
    assert r.counters["replace_rejected_protected_lines"] == 1


def test_replace_that_moves_a_citation_to_another_source_is_rejected() -> None:
    # the text stays, but the claim is now attributed to proposal-b (_line_key drops citations)
    new = (
        "- The project runs from 2024 to 2026 ([[sources/proposal-b]]).\n"
        "- Kick-off meeting held in Vienna with all partners ([[sources/proposal-a]]).\n"
        "Hand-written note: check the timeline with the partners."
    )
    r = edits.apply(SCHEDULE, prop(("Schedule", "replace", new)), CTX_B)
    assert not r.changed and r.counters["replace_rejected_protected_lines"] == 1


def test_replace_that_rewords_only_this_sources_lines_is_accepted() -> None:
    new = (
        "* The project runs from **2024** to 2026 ([[sources/proposal-a]]).\n"  # reflow (D3)
        "- The kick-off meeting was held in Vienna with every partner ([[sources/proposal-b]]).\n"
        "- A second meeting follows in Graz one year later.\n"
        "Hand-written note: check the timeline with the partners."
    )
    r = edits.apply(SCHEDULE, prop(("Schedule", "replace", new)), CTX_B)
    assert r.changed and not r.rejected and r.counters["op_replace"] == 1
    schedule = r.body.split("## Schedule\n\n")[1]
    assert schedule == (
        # kept lines come back byte for byte; the human line gets no citation
        "- The project runs from 2024 to 2026 ([[sources/proposal-a]]).\n"
        "- The kick-off meeting was held in Vienna with every partner ([[sources/proposal-b]]).\n"
        "- A second meeting follows in Graz one year later. ([[sources/proposal-b]])\n"
        "Hand-written note: check the   timeline with the partners.\n"
    )


def test_replace_that_drops_an_uncited_human_line_is_rejected() -> None:
    # D2: uncited lines are protected like lines citing another source
    new = (
        "- The project runs from 2024 to 2026 ([[sources/proposal-a]]).\n"
        "- Kick-off meeting held in Vienna with all partners and guests ([[sources/proposal-b]])."
    )
    r = edits.apply(SCHEDULE, prop(("Schedule", "replace", new)), CTX_B)
    assert not r.changed
    assert "Hand-written note" in r.rejected[0].reason


def test_lead_of_another_source_may_be_extended_not_rewritten() -> None:
    r = edits.apply(
        SCHEDULE, prop(lead="Project Alpha is a large research project ([[sources/proposal-a]])."),
        CTX_B,
    )  # fmt: skip
    assert not r.changed and r.counters["lead_rejected_protected"] == 1
    (rej,) = r.rejected
    assert rej.retry and rej.section == "lead" and "word for word" in rej.reason
    extended = (
        "Project Alpha is a research project ([[sources/proposal-a]]). "
        "It has three work packages ([[sources/proposal-b]])."
    )
    r = edits.apply(SCHEDULE, prop(lead=extended), CTX_B)
    assert r.changed and not r.rejected and f"\n{extended}\n" in r.body


def test_lead_citing_only_this_source_may_be_rewritten() -> None:
    body = "\n# P\n\nP is a project with partners ([[sources/proposal-b]]).\n"
    new = "P is a research project with four partners ([[sources/proposal-b]])."
    r = edits.apply(body, prop(lead=new), CTX_B)
    assert r.changed and not r.rejected and r.body == f"\n# P\n\n{new}\n"


def test_lead_lines_lose_their_list_marks() -> None:
    # #22 run: the model extended a lead with "\n- <new sentence>"; joined, the "-" ended
    # up mid-paragraph
    lead = (
        "Project Alpha is a research project ([[sources/proposal-a]]).\n"
        "- It was extended by one year ([[sources/proposal-b]])."
    )
    r = edits.apply(SCHEDULE, prop(lead=lead), CTX_B)
    assert r.changed and lead.replace("\n- ", " ") in r.body
