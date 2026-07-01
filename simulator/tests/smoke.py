r"""
Smoke test for the Local Work IQ Simulator engine (scenario C2: Contoso Precision Parts / Part 45621-B).

Metadata
--------
Created:   14-JUN-2026
Component: tests/smoke.py
Role:      Exercises engine.ask() for all 8 C2 golden questions (asserting each
           returns its expected cited fixtures), verifies persona permission trimming
           (contractor cannot see the customer escalation), and verifies the Tools
           surface (create_entity append + idempotency, update_entity patch, fetch).

Run:
    .\.venv\Scripts\python.exe simulator\tests\smoke.py
Exit code 0 = all passed, 1 = failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the simulator package importable regardless of cwd.
SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

import engine  # noqa: E402

SCENARIO = SIM_DIR / "scenarios" / "c2-contoso"

PASS = "ok "
FAIL = "X  "
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = PASS if cond else FAIL
    print(f"{mark}{name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def citation_ids(result: dict) -> set[str]:
    return {c["citation_id"] for c in result["citations"]}


def main() -> int:
    sc = engine.load_scenario(SCENARIO)

    # ---- Fixture load sanity ----
    check("load: people", len(sc.people) == 10, f"got {len(sc.people)}")
    check("load: emails", len(sc.emails) == 6, f"got {len(sc.emails)}")
    check("load: meetings", len(sc.meetings) == 3, f"got {len(sc.meetings)}")
    check("load: teams", len(sc.teams_messages) == 5, f"got {len(sc.teams_messages)}")
    check("load: files", len(sc.files) == 3, f"got {len(sc.files)}")
    check("load: onenote", len(sc.onenote_pages) == 2, f"got {len(sc.onenote_pages)}")
    check("load: golden", len(sc.golden) == 8, f"got {len(sc.golden)}")
    check("load: tracker", len(sc.tables["milestone_tracker"]) == 4,
          f"got {len(sc.tables['milestone_tracker'])}")
    check("load: personas", len(sc.personas) == 4, f"got {len(sc.personas)}")

    # ---- 8 golden questions match correctly (persona=new_pm, full access) ----
    expected_match = {
        "Q1": "What did the last 45621-B design review meeting conclude, and what action items came out of it with owners?",
        "Q2": "What did our customer's program office email us about in the last escalation thread, and what did we commit to?",
        "Q3": "What is currently blocking the PPAP qualification?",
        "Q4": "Who is the expert on the Inconel 718 supplier issue, and what have they said about it across chats and email in the last month?",
        "Q5": "I'm taking over the 45621-B program — give me the current state: last design-review decisions, open supplier risks, who owns the PPAP qualification plan, and the customer's most recent escalation.",
        "Q6": "Across the program, what changed in the last two weeks that I should know about — decisions, new risks, slipped milestones, and people who flagged concerns?",
        "Q7": "Summarise the open qualification blockers and create a tracked risk item in the milestone tracker for each one, assigned to the named owner.",
        "Q8": "Draft the weekly program status email to the customer covering decisions, risks, and milestone movement since the last update.",
    }
    for qid, qtext in expected_match.items():
        r = engine.ask(sc, qtext, persona_id="new_pm")
        check(f"{qid}: golden match", r["source"] == "golden" and r["matched"] == qid,
              f"source={r['source']} matched={r.get('matched')}")
        check(f"{qid}: has citations", len(r["citations"]) >= 1, "no citations")

    # ---- Multi-source questions cite >=2 distinct source kinds ----
    r3 = engine.ask(sc, expected_match["Q3"], persona_id="new_pm")
    kinds3 = {c["kind"] for c in r3["citations"]}
    check("Q3: multi-source kinds", len(kinds3) >= 2, f"kinds={kinds3}")

    r5 = engine.ask(sc, expected_match["Q5"], persona_id="new_pm")
    kinds5 = {c["kind"] for c in r5["citations"]}
    check("Q5: multi-source kinds (>=3)", len(kinds5) >= 3, f"kinds={kinds5}")

    # ---- Persona trimming: contractor cannot see customer escalation (EML-001/002) ----
    r2_pm = engine.ask(sc, expected_match["Q2"], persona_id="new_pm")
    check("Q2: new_pm sees escalation", {"EML-001", "EML-002"} <= citation_ids(r2_pm),
          f"cites={citation_ids(r2_pm)}")

    r2_contractor = engine.ask(sc, expected_match["Q2"], persona_id="contractor")
    check("Q2: contractor trimmed", {"EML-001", "EML-002"} & citation_ids(r2_contractor) == set(),
          f"cites={citation_ids(r2_contractor)}")
    check("Q2: contractor governance note", len(r2_contractor["trimmed"]) == 2 and "Governance" in r2_contractor["response"],
          f"trimmed={r2_contractor['trimmed']}")

    # quality_engineer should also be trimmed on the restricted customer escalation
    r2_qe = engine.ask(sc, expected_match["Q2"], persona_id="quality_engineer")
    check("Q2: quality_engineer trimmed", {"EML-001", "EML-002"} & citation_ids(r2_qe) == set(),
          f"cites={citation_ids(r2_qe)}")

    # ---- CRITICAL: restricted FACTS must not leak in the answer TEXT (not just citations) ----
    # new_pm gets the full answer with the committed recovery date and customer name.
    leak_terms = ["03-JUL", "Karen Vance", "flight-test"]
    check("Q2: new_pm full answer", any(t in r2_pm["response"] for t in ["03-JUL", "Karen Vance"]),
          "new_pm did not get full answer text")
    # contractor must NOT see those restricted facts in the response prose.
    check("Q2: contractor text redacted", not any(t in r2_contractor["response"] for t in leak_terms),
          f"LEAK in contractor response: {[t for t in leak_terms if t in r2_contractor['response']]}")
    check("Q2: quality_engineer text redacted", not any(t in r2_qe["response"] for t in leak_terms),
          f"LEAK in QE response: {[t for t in leak_terms if t in r2_qe['response']]}")

    # ---- Q5 handover: restricted escalation trimmed for contractor but core brief remains ----
    r5_contractor = engine.ask(sc, expected_match["Q5"], persona_id="contractor")
    check("Q5: contractor trims restricted", "EML-001" not in citation_ids(r5_contractor),
          f"cites={citation_ids(r5_contractor)}")
    check("Q5: contractor still has brief", "MTG-001" in citation_ids(r5_contractor),
          "lost non-restricted citations")
    check("Q5: contractor risk register trimmed", "FILE-002" not in citation_ids(r5_contractor),
          f"cites={citation_ids(r5_contractor)}")
    check("Q5: contractor text redacted", "Karen Vance" not in r5_contractor["response"],
          "customer name leaked into redacted handover")

    # ---- Paraphrase / morphology tolerance ----
    r_para = engine.ask(sc, "What are the blockers on the PPAP qualification right now?", persona_id="new_pm")
    check("paraphrase: 'blockers' matches Q3", r_para["matched"] == "Q3",
          f"matched={r_para.get('matched')}")

    # ---- Tools surface: fetch ----
    rows = engine.fetch(sc, "milestone_tracker", {"status": "At Risk"})
    check("fetch: At Risk row", len(rows) == 1 and rows[0]["id"] == "MS-002",
          f"got {[r.get('id') for r in rows]}")

    # ---- Tools surface: create_entity append + idempotency ----
    before = len(sc.tables["milestone_tracker"])
    res_new = engine.create_entity(sc, "milestone_tracker", {
        "milestone": "Material Lot Quarantine & Replacement",
        "owner": "PPL-008",
        "baseline_date": "2026-06-13",
        "current_date": "2026-06-13",
        "status": "Open",
        "risk": "Apex Alloys lot 24-118 non-conforming",
    })
    check("create: appended", res_new["created"] is True and len(sc.tables["milestone_tracker"]) == before + 1,
          f"created={res_new.get('created')} len={len(sc.tables['milestone_tracker'])}")

    # re-issue the same logical create -> deduped, no growth
    res_dup = engine.create_entity(sc, "milestone_tracker", {
        "milestone": "Material Lot Quarantine & Replacement",
        "owner": "PPL-008",
        "baseline_date": "2026-06-13",
        "current_date": "2026-06-13",
        "status": "Open",
        "risk": "Apex Alloys lot 24-118 non-conforming",
    })
    check("create: idempotent", res_dup["created"] is False and len(sc.tables["milestone_tracker"]) == before + 1,
          f"created={res_dup.get('created')} len={len(sc.tables['milestone_tracker'])}")

    # ---- Tools surface: update_entity ----
    res_upd = engine.update_entity(sc, "milestone_tracker", "MS-003", {"status": "Released"})
    check("update: patched", res_upd["updated"] is True and res_upd["row"]["status"] == "Released",
          f"res={res_upd}")
    res_upd_miss = engine.update_entity(sc, "milestone_tracker", "NOPE-999", {"status": "x"})
    check("update: not_found", res_upd_miss["updated"] is False, f"res={res_upd_miss}")

    # ---- _next_id is collision-safe with sparse / deleted ids ----
    sparse = [{"id": "MS-001"}, {"id": "MS-005"}]  # gap + non-sequential
    nid = engine._next_id(sparse, "MS")
    check("next_id: max-suffix+1", nid == "MS-006", f"got {nid}")
    # create on a sparse table must not reuse an existing id
    sparse_sc = engine.load_scenario(SCENARIO)
    sparse_sc.tables["milestone_tracker"][:] = [{"id": "MS-001", "milestone": "A", "owner": "X"},
                                      {"id": "MS-009", "milestone": "B", "owner": "Y"}]
    created = engine.create_entity(sparse_sc, "milestone_tracker", {"milestone": "C", "owner": "Z"})
    ids_after = {r["id"] for r in sparse_sc.tables["milestone_tracker"]}
    check("create: no id collision on sparse", created["row"]["id"] == "MS-010" and len(ids_after) == 3,
          f"id={created['row']['id']} ids={ids_after}")

    # ---- update_entity rekeys the citation index when id changes ----
    rekey_sc = engine.load_scenario(SCENARIO)
    engine.update_entity(rekey_sc, "milestone_tracker", "MS-004", {"id": "MS-900"})
    check("update: index rekeyed", "MS-900" in rekey_sc.index and "MS-004" not in rekey_sc.index,
          f"index has MS-900={'MS-900' in rekey_sc.index} MS-004={'MS-004' in rekey_sc.index}")

    # ---- unknown table raises ValueError (server converts to structured error) ----
    try:
        engine.fetch(sc, "nonexistent_table")
        check("fetch: unknown table raises", False, "no exception")
    except ValueError:
        check("fetch: unknown table raises", True)

    # ---- Ad-hoc (no golden) degrades gracefully when no model ----
    r_adhoc = engine.ask(sc, "what is the cafeteria menu today", persona_id="new_pm")
    check("adhoc: no crash", isinstance(r_adhoc["response"], str) and r_adhoc["source"] in {"retrieval-only", "llm"},
          f"source={r_adhoc['source']}")

    # ---- OneNote source is retrievable/citable ----
    r_note = engine.ask(sc, "show the daily recovery log notes for lot 24-126", persona_id="new_pm")
    note_ids = citation_ids(r_note)
    check("onenote: cited in ad-hoc retrieval", "ONN-001" in note_ids,
          f"cites={note_ids}")

    # ---- Summary ----
    print()
    if failures:
        print(f"FAILED ({len(failures)}): {', '.join(failures)}")
        return 1
    print("ALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
