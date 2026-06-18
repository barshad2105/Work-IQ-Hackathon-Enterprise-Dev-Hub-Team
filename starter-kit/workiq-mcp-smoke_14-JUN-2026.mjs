// =====================================================================
// metadata:
//   title: Work IQ MCP stdio smoke test
//   file: workiq-mcp-smoke_14-JUN-2026.mjs
//   created_date: 14-JUN-2026
//   created_time: 14:05 IST
//   purpose: Spawn `workiq mcp`, run the MCP initialize handshake over
//            stdio, list the exposed tools, and exit. Validates that the
//            local Work IQ MCP server is reachable and authenticated.
//   run: node workiq\workiq-mcp-smoke_14-JUN-2026.mjs
//   note: First run may trigger an interactive browser sign-in (the same
//         delegated auth `workiq ask` uses). Complete it once; the token
//         is then cached for subsequent runs.
// =====================================================================
import { spawn } from "node:child_process";

const TIMEOUT_MS = 90_000; // generous: first run may include interactive auth
const PROTOCOL_VERSION = "2024-11-05";

const proc = spawn("workiq", ["mcp"], { shell: true });

let stdoutBuf = "";
let stderrBuf = "";
let initialized = false;
let done = false;

const timer = setTimeout(() => {
  fail(`Timed out after ${TIMEOUT_MS / 1000}s with no tools/list response. ` +
       `If a browser opened, finish sign-in and re-run.`);
}, TIMEOUT_MS);

function send(obj) {
  proc.stdin.write(JSON.stringify(obj) + "\n");
}

function fail(msg) {
  if (done) return;
  done = true;
  clearTimeout(timer);
  console.error("\n[FAIL] " + msg);
  if (stderrBuf.trim()) console.error("\n--- server stderr ---\n" + stderrBuf.trim());
  try { proc.kill(); } catch {}
  process.exit(1);
}

function succeed(tools) {
  if (done) return;
  done = true;
  clearTimeout(timer);
  console.log(`\n[PASS] Work IQ MCP server responded. ${tools.length} tool(s) exposed:`);
  for (const t of tools) console.log(`   - ${t.name}${t.description ? ": " + String(t.description).split("\n")[0] : ""}`);
  try { proc.kill(); } catch {}
  process.exit(0);
}

proc.stderr.on("data", d => { stderrBuf += d.toString(); });
proc.on("error", e => fail(`Could not start \`workiq mcp\`: ${e.message}`));
proc.on("exit", code => { if (!done) fail(`\`workiq mcp\` exited early (code ${code}).`); });

proc.stdout.on("data", chunk => {
  stdoutBuf += chunk.toString();
  let nl;
  while ((nl = stdoutBuf.indexOf("\n")) >= 0) {
    const line = stdoutBuf.slice(0, nl).trim();
    stdoutBuf = stdoutBuf.slice(nl + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; } // ignore non-JSON log lines
    handle(msg);
  }
});

function handle(msg) {
  if (msg.id === 1) {
    if (msg.error) return fail(`initialize failed: ${JSON.stringify(msg.error)}`);
    console.log("[ok] initialize handshake succeeded; server: " +
      JSON.stringify(msg.result?.serverInfo ?? {}));
    initialized = true;
    send({ jsonrpc: "2.0", method: "notifications/initialized" });
    send({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
  } else if (msg.id === 2) {
    if (msg.error) return fail(`tools/list failed: ${JSON.stringify(msg.error)}`);
    succeed(msg.result?.tools ?? []);
  }
}

console.log("Starting `workiq mcp` and sending MCP initialize ...");
send({
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: {
    protocolVersion: PROTOCOL_VERSION,
    capabilities: {},
    clientInfo: { name: "workiq-smoke", version: "1.0.0" },
  },
});
