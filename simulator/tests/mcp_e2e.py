r"""
End-to-end MCP stdio test for the Local Work IQ Simulator server.

Metadata
--------
Created:   14-JUN-2026
Component: tests/mcp_e2e.py
Role:      Launches server.py as a real MCP stdio subprocess via the mcp client SDK,
           lists tools (asserts the 4 expected tools exist with the right shapes),
           calls ask_work_iq (golden Q5 handover) and create_entity, and verifies
           persona trimming end-to-end by running once as new_pm and once as contractor.

Run:
    .\.venv\Scripts\python.exe simulator\tests\mcp_e2e.py
Exit 0 = pass.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
SERVER = SIM_DIR / "server.py"
PYTHON = sys.executable

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok " if cond else "X  ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def _text(result) -> str:
    # CallToolResult.content is a list of content blocks; take the first text block.
    for block in result.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


async def run_persona(persona: str) -> dict:
    env = dict(os.environ)
    env["WORKIQ_SIM_PERSONA"] = persona
    params = StdioServerParameters(command=PYTHON, args=[str(SERVER)], env=env)
    out: dict = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            out["tools"] = sorted(t.name for t in tools.tools)

            q5 = ("I'm taking over the 45621-B program — give me the current state: last "
                  "design-review decisions, open supplier risks, who owns the qualification "
                  "test plan, and the customer's most recent escalation.")
            r = await session.call_tool("ask_work_iq", {"question": q5})
            out["ask"] = json.loads(_text(r))

            cr = await session.call_tool("create_entity", {
                "table": "milestone_tracker",
                "record": {
                    "milestone": "Material Lot Quarantine & Replacement",
                    "owner": "PPL-008",
                    "status": "Open",
                    "risk": "Apex Alloys lot 24-118 non-conforming",
                },
            })
            out["create"] = json.loads(_text(cr))

            fr = await session.call_tool("fetch", {
                "table": "milestone_tracker", "filter": {"status": "At Risk"}})
            out["fetch"] = json.loads(_text(fr))
    return out


async def main() -> int:
    pm = await run_persona("new_pm")
    check("tools: 4 expected", pm["tools"] == ["ask_work_iq", "create_entity", "fetch", "update_entity"],
          f"got {pm['tools']}")

    ask = pm["ask"]
    check("ask: has response/conversationId/citations",
          all(k in ask for k in ("response", "conversationId", "citations")),
          f"keys={list(ask.keys())}")
    cited = {c["citation_id"] for c in ask["citations"]}
    check("ask(new_pm): cites restricted escalation", "EML-001" in cited, f"cites={cited}")
    check("ask(new_pm): multi-source (>=3 kinds)",
          len({c["kind"] for c in ask["citations"]}) >= 3,
          f"kinds={ {c['kind'] for c in ask['citations']} }")

    check("create: created row", pm["create"].get("created") is True, f"res={pm['create']}")
    check("fetch: At Risk row", pm["fetch"]["count"] == 1, f"res={pm['fetch']}")

    # Persona trimming end-to-end
    con = await run_persona("contractor")
    cited_con = {c["citation_id"] for c in con["ask"]["citations"]}
    check("ask(contractor): escalation trimmed", "EML-001" not in cited_con, f"cites={cited_con}")
    check("ask(contractor): governance note present", "Governance" in con["ask"]["response"],
          "no governance note")
    check("ask(contractor): brief retained", "MTG-001" in cited_con, f"cites={cited_con}")

    print()
    if failures:
        print(f"FAILED ({len(failures)}): {', '.join(failures)}")
        return 1
    print("ALL MCP E2E CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
