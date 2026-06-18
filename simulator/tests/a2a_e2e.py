r"""
End-to-end A2A (Agent-to-Agent) test for the Local Work IQ Simulator A2A server.

Metadata
--------
Created:   15-JUN-2026
Component: tests/a2a_e2e.py
Role:      Starts a2a_server.py in-process on an ephemeral loopback port and drives it
           over real HTTP using the documented A2A wire format (JSON-RPC 2.0, method in
           the body). Asserts:
             * the A2A Agent Card is discoverable and well-formed,
             * SendMessage (Work IQ v1.0 name) and message/send (open-standard alias)
               both return a cited A2A message,
             * full-visibility callers see the restricted citation; restricted personas
               get it trimmed with a governance note (RBAC over A2A),
             * contextId is honoured for multi-turn continuity,
             * unknown methods and malformed params produce proper JSON-RPC errors,
           then runs a compact RBAC-trim loop across ALL six scenarios.

Run:
    .\.venv\Scripts\python.exe simulator\tests\a2a_e2e.py
Exit 0 = pass. Stdlib only (http.client + threading); no MCP/HTTP deps required.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.client import HTTPConnection
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

import engine  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok " if cond else "X  ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class A2AClient:
    """Minimal A2A JSON-RPC client over loopback HTTP."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._counter = 0

    def _conn(self) -> HTTPConnection:
        return HTTPConnection(self.host, self.port, timeout=30)

    def get_card(self) -> dict:
        conn = self._conn()
        conn.request("GET", "/.well-known/agent-card.json")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return json.loads(body)

    def send_message(self, text: str, persona: str | None = None,
                     context_id: str | None = None, method: str = "SendMessage") -> dict:
        self._counter += 1
        message: dict = {"role": "user", "parts": [{"kind": "text", "text": text}]}
        if persona is not None:
            message["metadata"] = {"persona": persona}
        if context_id is not None:
            message["contextId"] = context_id
        return self.rpc(method, {"message": message})

    def rpc(self, method: str, params: dict) -> dict:
        self._counter += 1
        payload = {"jsonrpc": "2.0", "id": self._counter, "method": method, "params": params}
        conn = self._conn()
        conn.request("POST", "/a2a/", body=json.dumps(payload),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return json.loads(body)

    def post_raw(self, body: str, headers: dict | None = None) -> tuple[int, str]:
        """POST a raw body and return (status, text) without JSON parsing — for testing
        malformed/batch/notification cases the typed helpers can't express."""
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        conn = self._conn()
        conn.request("POST", "/a2a/", body=body, headers=h)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8")
        status = resp.status
        conn.close()
        return status, text


def _cited(result_msg: dict) -> set[str]:
    cites = result_msg.get("metadata", {}).get("citations", [])
    return {c["citation_id"] for c in cites}


def _text(result_msg: dict) -> str:
    for part in result_msg.get("parts", []):
        if part.get("kind") == "text":
            return part.get("text", "")
    return ""


def _ok_result(name: str, resp: dict) -> dict:
    """Assert a JSON-RPC response succeeded (has a `result`, no `error`) BEFORE inspecting
    it — otherwise a server fault would let RBAC assertions pass vacuously."""
    ok = isinstance(resp, dict) and "result" in resp and "error" not in resp
    check(name, ok, f"resp={resp}")
    return resp.get("result", {}) if ok else {}


def _start_server(scenario_dir: Path):
    """Reload a2a_server bound to scenario_dir on an ephemeral port; return (client, httpd, thread)."""
    os.environ["WORKIQ_SIM_SCENARIO"] = str(scenario_dir)
    os.environ["WORKIQ_SIM_PERSONA"] = "new_pm"  # deterministic server default
    os.environ["WORKIQ_A2A_PORT"] = "0"  # ephemeral
    # Fresh import so module-level SCENARIO reflects this scenario dir.
    for mod in ("a2a_server",):
        sys.modules.pop(mod, None)
    import a2a_server  # noqa: PLC0415
    httpd = a2a_server.build_server()
    host, port = httpd.server_address
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return A2AClient(host, port), httpd, thread


def _restricted_probe(sc: engine.Scenario):
    """Pick a golden question with a restricted citation, plus a persona for whom it trims.
    Returns (question, restricted_cite, blocked_persona) or None if the scenario has none."""
    for g in sc.golden:
        restricted = g.get("restricted_citations") or []
        cites = g.get("citations") or []
        for rc in restricted:
            if rc not in cites:
                continue
            kind_rec = sc.index.get(rc)
            if not kind_rec:
                continue
            record = kind_rec[1]
            for pid in sc.persona_ids():
                if not engine.can_see(record, pid):
                    return g["question"], rc, pid
    return None


def main() -> int:
    # ----- Deep checks on c2-contoso (mirror mcp_e2e depth) -----
    c2 = SIM_DIR / "scenarios" / "c2-contoso"
    client, httpd, thread = _start_server(c2)
    try:
        card = client.get_card()
        check("agent card: name", card.get("name") == "workiq-simulator", f"card={card.get('name')}")
        check("agent card: JSON-RPC transport", card.get("preferredTransport") == "JSONRPC",
              f"transport={card.get('preferredTransport')}")
        check("agent card: ask skill present",
              any(s.get("id") == "ask_work_iq" for s in card.get("skills", [])),
              f"skills={[s.get('id') for s in card.get('skills', [])]}")

        q5 = ("I'm taking over the 45621-B program — give me the current state: last "
              "design-review decisions, open supplier risks, who owns the qualification "
              "test plan, and the customer's most recent escalation.")

        # Full visibility (persona "all").
        full = client.send_message(q5, persona="all")
        check("SendMessage: jsonrpc result present", "result" in full, f"resp={full}")
        msg = full.get("result", {})
        check("SendMessage: A2A message shape",
              msg.get("kind") == "message" and msg.get("role") == "agent" and "contextId" in msg,
              f"msg keys={list(msg.keys())}")
        full_cites = _cited(msg)
        check("SendMessage(all): cites restricted escalation", "EML-001" in full_cites,
              f"cites={full_cites}")
        kinds = {c["kind"] for c in msg.get("metadata", {}).get("citations", [])}
        check("SendMessage(all): multi-source (>=3 kinds)", len(kinds) >= 3, f"kinds={kinds}")

        # Open-standard alias must work identically.
        alias = client.send_message(q5, persona="all", method="message/send")
        check("message/send alias: cites restricted escalation",
              "EML-001" in _cited(alias.get("result", {})), f"resp={alias}")

        # Multi-turn: caller-supplied contextId is echoed back.
        cid = "ctx-test-multiturn-001"
        turn = client.send_message("And who owns the qualification test plan?",
                                   persona="all", context_id=cid)
        check("contextId: echoed for multi-turn",
              turn.get("result", {}).get("contextId") == cid,
              f"got={turn.get('result', {}).get('contextId')}")

        # RBAC over A2A: contractor persona gets the escalation trimmed.
        con = client.send_message(q5, persona="contractor")
        con_msg = _ok_result("SendMessage(contractor): call succeeded", con)
        con_cites = _cited(con_msg)
        check("SendMessage(contractor): escalation trimmed", "EML-001" not in con_cites,
              f"cites={con_cites}")
        check("SendMessage(contractor): governance note present",
              "Governance" in _text(con_msg), "no governance note")
        check("SendMessage(contractor): brief retained", "MTG-001" in con_cites,
              f"cites={con_cites}")

        # JSON-RPC error semantics.
        bad_method = client.rpc("DoesNotExist", {"message": {"parts": [{"kind": "text", "text": "hi"}]}})
        check("error: unknown method -> -32601",
              bad_method.get("error", {}).get("code") == -32601, f"resp={bad_method}")
        bad_params = client.rpc("SendMessage", {"message": {"parts": []}})
        check("error: empty parts -> -32602",
              bad_params.get("error", {}).get("code") == -32602, f"resp={bad_params}")

        # JSON-RPC 2.0 batch / notification / malformed-request compliance.
        st, txt = client.post_raw("[]")
        empty_batch = json.loads(txt) if txt else {}
        check("empty batch -> single -32600",
              isinstance(empty_batch, dict) and empty_batch.get("error", {}).get("code") == -32600,
              f"status={st} body={txt}")

        st, txt = client.post_raw(
            '[{"jsonrpc":"2.0","method":"SendMessage","params":'
            '{"message":{"parts":[{"kind":"text","text":"hi"}],"metadata":{"persona":"all"}}}}]')
        check("notification-only batch -> 204 no body", st == 204 and txt == "",
              f"status={st} body={txt!r}")

        st, txt = client.post_raw('{"method":"SendMessage","params":{}}')
        bad_shape = json.loads(txt) if txt else {}
        check("invalid request (no jsonrpc) -> -32600 with id null",
              bad_shape.get("error", {}).get("code") == -32600 and bad_shape.get("id") is None,
              f"status={st} body={txt}")

        st, txt = client.post_raw(
            '{"jsonrpc":"2.0","method":"SendMessage","params":'
            '{"message":{"parts":[{"kind":"text","text":"hi"}],"metadata":{"persona":"all"}}}}')
        check("valid notification (no id) -> 204 no body", st == 204 and txt == "",
              f"status={st} body={txt!r}")

        st, txt = client.post_raw(
            '{"jsonrpc":"2.0","id":9,"method":"SendMessage","params":{}}',
            headers={"Content-Length": "abc"})
        cl_err = json.loads(txt) if txt else {}
        check("invalid Content-Length -> parse error (no crash)",
              cl_err.get("error", {}).get("code") == -32700, f"status={st} body={txt}")

        # Empty/whitespace persona must NOT widen visibility to full ("all"); it falls
        # through to the server default persona (set deterministically in _start_server).
        ws = client.send_message(q5, persona="   ")
        ws_msg = _ok_result("whitespace persona: call succeeded", ws)
        check("whitespace persona resolves to default (not full visibility)",
              ws_msg.get("metadata", {}).get("persona") == "new_pm",
              f"persona={ws_msg.get('metadata', {}).get('persona')}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    # ----- Cross-scenario RBAC-trim loop over A2A -----
    scenarios = sorted(p for p in (SIM_DIR / "scenarios").iterdir() if p.is_dir())
    for sdir in scenarios:
        sc = engine.load_scenario(sdir)
        probe = _restricted_probe(sc)
        if probe is None:
            check(f"{sdir.name}: has a restricted-citation golden", False, "none found")
            continue
        question, rcite, blocked = probe
        cli, hd, hd_thread = _start_server(sdir)
        try:
            full = _ok_result(f"{sdir.name}: full call ok", cli.send_message(question, persona="all"))
            check(f"{sdir.name}: full persona sees restricted {rcite} over A2A",
                  rcite in _cited(full), f"cites={_cited(full)}")
            trimmed = _ok_result(f"{sdir.name}: trimmed call ok",
                                 cli.send_message(question, persona=blocked))
            check(f"{sdir.name}: RBAC trims {rcite} for '{blocked}' over A2A",
                  rcite not in _cited(trimmed), f"cites={_cited(trimmed)}")
        finally:
            hd.shutdown()
            hd.server_close()

    print()
    if failures:
        print(f"FAILED ({len(failures)}): {', '.join(failures)}")
        return 1
    print("ALL A2A E2E CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
