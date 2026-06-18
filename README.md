<!--
  Metadata
  File:    README.md
  Created: 18-JUN-2026 (time: repo packaging)
  Role:    Top-level getting-started guide for the Work IQ Hackathon repo.
-->

# Microsoft Work IQ Hackathon

Everything a team needs to take on a **Work IQ** hackathon challenge — the challenge
pack, a setup guide, an architecture guide, starter code, and a **local simulator** so
you can build and test **without a Microsoft 365 tenant**.

> **Work IQ** grounds answers in your *live work context* — email, meetings, chats,
> files, people, calendar and Copilot memory — reached over **MCP** and **A2A**.

---

## What's in this repo

```
workiq-hackathon/
  challenge-pack/     # The 3 PDFs you read first (challenge pack, setup guide, architecture guide)
  simulator/          # Local Work IQ simulator — 6 challenge scenarios, MCP + A2A servers, tests
  starter-kit/        # Drop-in agent + smoke-test scripts (Node .mjs / PowerShell) and an MCP config
  README.md           # You are here
```

| Folder | Start here |
|---|---|
| `challenge-pack/WorkIQ-Hackathon-Challenge-Pack_14-JUN-2026.pdf` | The 6 challenges, judging criteria, capability tiers. **Read first.** |
| `challenge-pack/WorkIQ-Hackathon-Participant-Setup-Guide_14-JUN-2026.pdf` | Step-by-step environment setup (real tenant **and** local simulator). |
| `challenge-pack/WorkIQ-Architecture-Guide_14-JUN-2026.pdf` | How Work IQ works under the hood (for architects / lead devs). |

---

## Pick your path

| | Path A — Local simulator | Path B — Real Work IQ |
|---|---|---|
| **Needs a tenant?** | ❌ No | ✅ Yes (M365 + Copilot, admin consent) |
| **Best for** | Building & testing logic fast, offline | The final, production-grade demo |
| **Setup** | 3 commands (below) | Follow the **Setup Guide PDF** |

You can build your whole solution against **Path A**, then swap the MCP endpoint to the
real server for **Path B** — your agent code doesn't change.

---

## Quick start — Path A (local simulator)

**Prerequisite:** Python 3.10+ on your PATH.

From the repo root (`workiq-hackathon/`):

```powershell
# 1. Create an isolated environment
python -m venv .venv

# 2. Install the simulator's only dependency (mcp)
.\.venv\Scripts\python.exe -m pip install -r simulator\requirements.txt

# 3. Confirm everything works (each prints "ALL ... PASSED")
.\.venv\Scripts\python.exe simulator\tests\smoke.py
.\.venv\Scripts\python.exe simulator\tests\mcp_e2e.py
.\.venv\Scripts\python.exe simulator\tests\a2a_e2e.py
```

> macOS / Linux: use `python3 -m venv .venv` then `.venv/bin/python` instead of
> `.\.venv\Scripts\python.exe`.

### Ask the simulator a question

```powershell
# Default challenge (c2-contoso), default persona
.\.venv\Scripts\python.exe simulator\demo.py --ask "What is blocking qualification?"

# Try the RBAC governance demo — same question, different persona = redacted answer
.\.venv\Scripts\python.exe simulator\demo.py --persona contractor --ask "Give me the 45621-B handover brief."
```

### Validate any of the 6 challenge scenarios

```powershell
.\.venv\Scripts\python.exe simulator\tests\validate_scenario.py scenarios\c1-northbridge
.\.venv\Scripts\python.exe simulator\tests\validate_scenario.py scenarios\c2-contoso
# ... c3-meridian, c4-arundel, c5-westbrook, c6-edkh
```

### Plug it into your agent (MCP)

Register the simulator like the real Work IQ MCP server — same tool name
(`ask_work_iq`), so your agent code is unchanged. See
[`simulator/README.md`](simulator/README.md) for the full MCP + A2A config and wire
contracts.

---

## Quick start — Path B (real Work IQ)

Open **`challenge-pack/WorkIQ-Hackathon-Participant-Setup-Guide_14-JUN-2026.pdf`** and
follow it end to end: tenant prerequisites, admin consent for `WorkIQAgent.Ask`, the
service principal, Copilot licensing, and registering the real MCP endpoint. The
`starter-kit/` scripts get you to a first call quickly.

---

## Starter kit

Drop-in helpers in `starter-kit/` (rename / repath as needed):

| File | What it does |
|---|---|
| `workiq-agent_14-JUN-2026.mjs` | Minimal agent that calls Work IQ over MCP. |
| `workiq-ask-harness_14-JUN-2026.mjs` | Fire a single question and print the cited answer. |
| `workiq-mcp-smoke_14-JUN-2026.mjs` | Confirm your MCP connection + tool list. |
| `workiq-smoke-test_14-JUN-2026.ps1` | PowerShell smoke test. |
| `workiq-mcp-config_14-JUN-2026.json` | Reference MCP server config. |

---

## Need more detail?

- **The challenges** → `challenge-pack/WorkIQ-Hackathon-Challenge-Pack_14-JUN-2026.pdf`
- **Full setup (both paths)** → `challenge-pack/WorkIQ-Hackathon-Participant-Setup-Guide_14-JUN-2026.pdf`
- **Simulator internals, MCP/A2A config, scenario data** → [`simulator/README.md`](simulator/README.md)
- **Architecture** → `challenge-pack/WorkIQ-Architecture-Guide_14-JUN-2026.pdf`

Happy hacking. 🛠️
