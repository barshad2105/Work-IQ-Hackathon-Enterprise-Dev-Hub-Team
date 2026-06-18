<#
=====================================================================
metadata:
  title: Work IQ end-to-end smoke test
  file: workiq-smoke-test_14-JUN-2026.ps1
  created_date: 14-JUN-2026
  created_time: 14:05 IST
  purpose: Validate the local Work IQ CLI end to end - environment,
           a live `ask` call, and the MCP stdio server + tool discovery.
  run:     pwsh -File workiq\workiq-smoke-test_14-JUN-2026.ps1
  note:    The `ask` and `mcp` steps use delegated auth. The first run
           may open a browser for sign-in - complete it once; the token
           is cached afterwards. Run this in YOUR interactive terminal,
           not an unattended/background shell.
=====================================================================
#>
param(
  [string]$Question = "Give me a one-line summary of what I worked on this week."
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pass = $true

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Good($t)    { Write-Host "[PASS] $t"   -ForegroundColor Green }
function Bad($t)     { Write-Host "[FAIL] $t"   -ForegroundColor Red; $script:pass = $false }

# --- 1. Environment (non-interactive) -------------------------------
Section "1. Environment"
$cmd = Get-Command workiq -ErrorAction SilentlyContinue
if ($cmd) { Good "workiq found at $($cmd.Source)" } else { Bad "workiq not on PATH"; exit 1 }

$ver = (& workiq --version) 2>&1
Write-Host "    version: $ver"

Write-Host "    config:"
(& workiq config) 2>&1 | ForEach-Object { Write-Host "      $_" }

# --- 2. Live `ask` (may trigger interactive sign-in) ----------------
Section "2. Live `ask` call"
Write-Host "    Question: $Question"
Write-Host "    (If a browser opens, complete sign-in; this is expected on first run.)"
try {
  $answer = (& workiq ask $Question) 2>&1 | Out-String
  if ($LASTEXITCODE -eq 0 -and $answer.Trim()) {
    Good "ask returned a response"
    Write-Host "    --- answer (truncated) ---"
    ($answer.Trim() -split "`n" | Select-Object -First 8) | ForEach-Object { Write-Host "    $_" }
  } else {
    Bad "ask did not return a clean response (exit $LASTEXITCODE)"
    Write-Host $answer
  }
} catch { Bad "ask threw: $($_.Exception.Message)" }

# --- 3. MCP stdio server + tool discovery ---------------------------
Section "3. MCP server (`workiq mcp`) + tools/list"
$node = Get-Command node -ErrorAction SilentlyContinue
$mcpSmoke = Join-Path $scriptDir "workiq-mcp-smoke_14-JUN-2026.mjs"
if (-not $node) {
  Bad "node not found - skipping MCP handshake test"
} elseif (-not (Test-Path $mcpSmoke)) {
  Bad "MCP smoke script not found at $mcpSmoke"
} else {
  & node $mcpSmoke
  if ($LASTEXITCODE -eq 0) { Good "MCP handshake + tools/list succeeded" }
  else { Bad "MCP handshake failed (see output above)" }
}

# --- Summary --------------------------------------------------------
Section "Summary"
if ($pass) { Write-Host "ALL CHECKS PASSED - Work IQ is ready to use." -ForegroundColor Green; exit 0 }
else       { Write-Host "ONE OR MORE CHECKS FAILED - see above." -ForegroundColor Red; exit 1 }
