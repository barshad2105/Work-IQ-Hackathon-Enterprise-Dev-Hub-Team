r"""
Generic scenario validator for the Local Work IQ Simulator.

Metadata
--------
Created:   14-JUN-2026
Component: tests/validate_scenario.py
Role:      Scenario-agnostic acceptance gate. Given any scenario directory it
           verifies the contract every C1..C6 scenario must satisfy, so new
           scenarios need no bespoke test file:
             1. Each golden question self-matches by id (unique best match).
             2. Every golden citation resolves in the citation index.
             3. trimmed_answer is present whenever restricted_citations is non-empty.
             4. restricted_citations actually trim for at least one declared persona,
                and trimming yields the trimmed_answer (not the full answer).
             5. At least one fixture is restricted (acl != ['all']) and is hidden
                from at least one persona (RBAC demo is wired).
             6. fetch / create_entity / update_entity round-trip on every discovered
                Tools table (in-memory; nothing is persisted).

Run:
    .\.venv\Scripts\python.exe simulator\tests\validate_scenario.py <scenario_dir>
    # default scenario_dir = scenarios/c1-northbridge
Exit code 0 = all passed, 1 = failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

import engine  # noqa: E402

PASS = "ok "
FAIL = "X  "
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = PASS if cond else FAIL
    print(f"{mark}{name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def validate(scenario_dir: Path) -> None:
    sc = engine.load_scenario(scenario_dir)
    print(f"\n=== validating {scenario_dir.name} "
          f"(golden={len(sc.golden)}, personas={sc.persona_ids()}, "
          f"tables={sc.table_names()}) ===")

    persona_ids = sc.persona_ids()

    # 1. Golden self-match (unique best). 2. Citations resolve. 3/4. Restriction wiring.
    for g in sc.golden:
        qid = g["id"]
        match = engine.match_golden(sc, g["question"])
        check(f"{qid}: self-match", match is not None and match["id"] == qid,
              f"matched {match['id'] if match else None}")

        # unique best: no OTHER golden outranks-or-ties this one for its own question,
        # using the same (hits, fraction) ranking the engine's matcher uses.
        my_key = engine._match_stats(g["question"], g)
        rivals = [o["id"] for o in sc.golden
                  if o["id"] != qid and engine._match_stats(g["question"], o) >= my_key]
        check(f"{qid}: unique top match", not rivals, f"rivals {rivals}")

        for cid in g.get("citations", []):
            check(f"{qid}: citation {cid} resolves", cid in sc.index)

        restricted = g.get("restricted_citations", [])
        if restricted:
            check(f"{qid}: has trimmed_answer", bool(g.get("trimmed_answer")))
            # find a persona that cannot see at least one restricted citation
            blocked_persona = None
            for pid in persona_ids:
                if any(not engine.can_see(sc.index[c][1], pid)
                       for c in restricted if c in sc.index):
                    blocked_persona = pid
                    break
            check(f"{qid}: a persona is blocked from a restricted citation",
                  blocked_persona is not None)
            if blocked_persona is not None:
                res = engine.ask(sc, g["question"], persona_id=blocked_persona)
                check(f"{qid}: blocked persona is trimmed", bool(res["trimmed"]))
                check(f"{qid}: trimmed response != full answer",
                      res["response"].split("\n\n[Governance]")[0] != g["answer"])

        # Cross-persona RBAC leak guard: for EVERY persona, the response must never
        # narrate facts the persona can't see. When a persona is blocked from MORE
        # citations than restricted_citations anticipates, the engine must fail closed
        # (generic message) — it must NOT serve the authored trimmed_answer or full answer.
        restricted_set = set(restricted)
        authored_trim = (g.get("trimmed_answer") or "").strip()
        for pid in persona_ids:
            res = engine.ask(sc, g["question"], persona_id=pid)
            trimmed_set = set(res["trimmed"])
            if not trimmed_set:
                continue
            body = res["response"].split("\n\n[Governance]")[0].strip()
            if trimmed_set <= restricted_set:
                # anticipated trim: authored redaction is allowed (but never the full answer)
                check(f"{qid}/{pid}: anticipated trim not full answer",
                      body != g["answer"].strip())
            else:
                # over-trimmed: must be the generic fail-closed message
                fail_closed = body.startswith("A complete answer to this question")
                check(f"{qid}/{pid}: over-trim fails closed",
                      fail_closed and body != authored_trim and body != g["answer"].strip(),
                      f"trimmed={sorted(trimmed_set)} restricted={sorted(restricted_set)}")

    # 5. At least one restricted fixture hidden from at least one persona.
    restricted_hits = 0
    for record_id, (_, rec) in sc.index.items():
        acl = rec.get("acl", ["all"])
        if "all" not in acl:
            if any(not engine.can_see(rec, pid) for pid in persona_ids):
                restricted_hits += 1
    check("scenario has >=1 restricted fixture that trims for some persona",
          restricted_hits >= 1, f"restricted_hits={restricted_hits}")

    # 6. Tools round-trip on every discovered table.
    for table in sc.table_names():
        rows = engine.fetch(sc, table)
        check(f"table {table}: fetch returns rows", len(rows) > 0, f"got {len(rows)}")

        before = len(sc.tables[table])
        created = engine.create_entity(sc, table, {"_probe": "validate"})
        new_id = created["row"]["id"]
        check(f"table {table}: create_entity appends",
              created["created"] is True and len(sc.tables[table]) == before + 1,
              f"created={created.get('created')} len={len(sc.tables[table])}")
        check(f"table {table}: created row is indexed", new_id in sc.index)

        upd = engine.update_entity(sc, table, new_id, {"status": "ProbeDone"})
        check(f"table {table}: update_entity patches",
              upd.get("updated") is True and upd["row"].get("status") == "ProbeDone")

        fetched = engine.fetch(sc, table, {"id": new_id})
        check(f"table {table}: fetch filter finds updated row",
              len(fetched) == 1 and fetched[0].get("status") == "ProbeDone")


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else "scenarios/c1-northbridge"
    scenario_dir = Path(arg)
    if not scenario_dir.is_absolute():
        scenario_dir = SIM_DIR / scenario_dir
    if not scenario_dir.is_dir():
        print(f"X  scenario directory not found: {scenario_dir}")
        return 1

    validate(scenario_dir)

    print()
    if failures:
        print(f"VALIDATION FAILED — {len(failures)} check(s): {failures}")
        return 1
    print("ALL VALIDATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
