"""
Unified Web UI for the Work IQ Agent using Flask.
Supports both MCP and A2A transports — controlled via the incoming request payload.

Request format:
    {"message": "...", "transport": "mcp"}   — uses MCP stdio tool
    {"message": "...", "transport": "a2a"}   — uses A2A protocol (default)
"""

import os
import asyncio
import sys
import shlex
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, session, send_file
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient

# Data Connector Framework
from connectors import (
    get_connector_manager,
    ConnectorConfig,
    ConnectorType,
    MSGraphConnector,
    CustomAPIConnector,
)

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your-secret-key-change-in-production")

# Shared state
_client = None
event_loop = None
available_personas = []
sim_engine = None
sim_scenario = None
last_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _parse_citations_from_text(text: str) -> tuple[str, list]:
    """Parse a 'Citations:' section from the LLM response text.

    Returns (body_without_citations, structured_citations_list).
    Each citation is: {"citation_id": "MTG-001", "kind": "source", "title": "..."}.
    Handles various LLM formatting styles: with/without quotes, bullets, markdown bold, etc.
    """
    # Split on "Citations:" heading — tolerate markdown bold, bullets, varied whitespace
    parts = re.split(r'\n\s*\*{0,2}Citations:?\*{0,2}\s*\n?', text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2:
        # Fallback: try splitting on "Sources:" as some models use that heading
        parts = re.split(r'\n\s*\*{0,2}Sources:?\*{0,2}\s*\n?', text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2:
        return text.strip(), []

    body = parts[0].strip()
    citations_block = parts[1].strip()

    citations = []

    # Pattern 1: [ID]: "Title" or [ID]: "Title"
    for match in re.finditer(r'\[([A-Z]+-\d+)\]:\s*["\u201c]([^"\u201d]*)["\u201d]', citations_block):
        cit_id = match.group(1)
        title = match.group(2)
        citations.append({"citation_id": cit_id, "title": title})

    # Pattern 2: [ID]: Title (no quotes) — only if pattern 1 found nothing
    if not citations:
        for match in re.finditer(r'\[([A-Z]+-\d+)\]:\s*(.+)', citations_block):
            cit_id = match.group(1)
            title = match.group(2).strip().strip('"').strip('\u201c\u201d')
            citations.append({"citation_id": cit_id, "title": title})

    # Pattern 3: - ID: "Title" or - ID — Title (no brackets, with bullet)
    if not citations:
        for match in re.finditer(r'[-•*]\s*([A-Z]+-\d+)[:\s—–-]+\s*(.+)', citations_block):
            cit_id = match.group(1)
            title = match.group(2).strip().strip('"').strip('\u201c\u201d')
            citations.append({"citation_id": cit_id, "title": title})

    # Pattern 4: bare ID: Title (no brackets, no bullets)
    if not citations:
        for match in re.finditer(r'^([A-Z]+-\d+)[:\s—–-]+\s*(.+)', citations_block, re.MULTILINE):
            cit_id = match.group(1)
            title = match.group(2).strip().strip('"').strip('\u201c\u201d')
            citations.append({"citation_id": cit_id, "title": title})

    # Assign kind based on title or citation_id prefix
    for c in citations:
        title_lower = c["title"].lower()
        cid = c["citation_id"]
        if cid.startswith("MTG") or "meeting" in title_lower:
            c["kind"] = "meeting"
        elif cid.startswith("EML") or "email" in title_lower:
            c["kind"] = "email"
        elif cid.startswith("FILE") or "file" in title_lower or "doc" in title_lower:
            c["kind"] = "file"
        elif cid.startswith("MSG") or "teams" in title_lower or "channel" in title_lower:
            c["kind"] = "teams_message"
        elif cid.startswith("ONC") or "onenote" in title_lower:
            c["kind"] = "onenote_page"
        elif cid.startswith("ACT") or "action" in title_lower:
            c["kind"] = "meeting"
        else:
            c["kind"] = "source"

    return body, citations


def _build_trace(question: str, active_persona: str, transport: str, citations: list, token_usage: dict | None = None) -> dict:
    """Build a trace payload for the UI flyout."""
    if token_usage is None:
        token_usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    fixture_map = {
        "email": "emails.json",
        "meeting": "meetings.json",
        "teams_message": "teams.json",
        "file": "files.json",
        "onenote_page": "onenote.json",
    }
    files_used = []
    seen = set()
    for c in citations:
        f = fixture_map.get(c.get("kind", ""), "tables/*.json")
        if f not in seen:
            seen.add(f)
            files_used.append(f)

    steps = [
        f"Received question over REST: {question[:120]}",
        f"Applied active persona: {active_persona}",
        f"Selected transport mode: {transport.upper()}",
        f"Execution path: agent+{transport}",
    ]
    if citations:
        steps.append(f"Resolved citations: {len(citations)}")
    else:
        steps.append("No citations resolved for this response")

    if token_usage.get('total_tokens', 0) > 0:
        total = token_usage['total_tokens']
        prompt = token_usage.get('prompt_tokens', 0)
        completion = token_usage.get('completion_tokens', 0)
        steps.append(f"Token consumption: {total} total ({prompt} prompt + {completion} completion)")

    return {
        "transport": transport.upper(),
        "mode": f"agent+{transport}",
        "active_persona": active_persona,
        "source": None,
        "matched": None,
        "files_used": files_used,
        "steps": steps,
        "token_usage": token_usage,
    }


def _fixture_for_kind(kind: str) -> str:
    mapping = {
        "email": "emails.json",
        "meeting": "meetings.json",
        "action_item": "meetings.json#action_items",
        "teams_message": "teams.json",
        "file": "files.json",
        "onenote_page": "onenote.json",
        "person": "people.json",
        "milestone": "tables/milestone_tracker.json",
        "capa": "tables/capa_tracker.json",
    }
    return mapping.get(kind, "tables/*.json")


def _extract_token_usage(response_obj) -> dict:
    """Extract token usage information from agent response."""
    global last_token_usage
    usage_info = {}
    try:
        if last_token_usage.get('total_tokens', 0) > 0:
            return last_token_usage.copy()
        if hasattr(response_obj, 'usage_details'):
            usage = response_obj.usage_details
            if usage and isinstance(usage, dict):
                usage_info['prompt_tokens'] = usage.get('input_token_count', 0) or usage.get('prompt_tokens', 0)
                usage_info['completion_tokens'] = usage.get('output_token_count', 0) or usage.get('completion_tokens', 0)
                usage_info['total_tokens'] = usage.get('total_token_count', 0) or usage.get('total_tokens', 0)
                if usage_info.get('total_tokens', 0) > 0:
                    return usage_info
        if hasattr(response_obj, 'usage'):
            usage = response_obj.usage
            if usage:
                if isinstance(usage, dict):
                    usage_info.update(usage)
                else:
                    usage_info['prompt_tokens'] = getattr(usage, 'prompt_tokens', 0)
                    usage_info['completion_tokens'] = getattr(usage, 'completion_tokens', 0)
                    usage_info['total_tokens'] = getattr(usage, 'total_tokens', 0)
    except Exception:
        pass
    result = {
        'prompt_tokens': usage_info.get('prompt_tokens', 0),
        'completion_tokens': usage_info.get('completion_tokens', 0),
        'total_tokens': usage_info.get('total_tokens', 0),
    }
    if result.get('total_tokens', 0) > 0:
        last_token_usage = result.copy()
    return result


def _extract_citation_ids_from_text(text: str) -> list[str]:
    """Extract citation ID patterns from response text like EML-003, MTG-001, ACT-002."""
    if not text:
        return []
    pattern = r'\b([A-Z]{2,4})-(\d{3,4})\b'
    matches = re.findall(pattern, text)
    seen = set()
    citation_ids = []
    for prefix, num in matches:
        cid = f"{prefix}-{num}"
        if cid not in seen:
            citation_ids.append(cid)
            seen.add(cid)
    return citation_ids


def _maybe_enforce_source_intent(sc, engine_module, question: str, persona_id, result: dict) -> dict:
    """If a source-specific question returns mismatched golden sources,
    re-answer via source-filtered retrieval to keep citations aligned with user intent."""
    try:
        detect_hints = getattr(engine_module, "_detect_source_hints", None)
        if not callable(detect_hints):
            return result
        hints = detect_hints(question) or set()
        if not hints:
            return result
        if result.get("source") != "golden":
            return result
        matched_id = result.get("matched")
        if not matched_id:
            return result
        golden_entry = next((g for g in sc.golden if g.get("id") == matched_id), None)
        if not golden_entry:
            return result
        cited_kinds = set()
        for cid in golden_entry.get("citations", []):
            entry = sc.index.get(cid)
            if entry is None:
                continue
            kind, _ = entry
            cited_kinds.add(kind)
        if cited_kinds & set(hints):
            return result
        all_snippets = engine_module._all_snippets(sc, persona_id)
        filter_by_hints = getattr(engine_module, "_filter_snippets_by_hints", None)
        if callable(filter_by_hints):
            all_snippets = filter_by_hints(sc, all_snippets, hints)
        top = engine_module._retrieve(all_snippets, question)
        cited_ids = [s.get("id") for s in top if s.get("id")]
        visible, _ = engine_module.resolve_citations(sc, cited_ids, persona_id)
        if top:
            bullets = "\n".join(f"- [{s['id']}] {s['text'][:140]}" for s in top)
            response = (
                "Answer constrained to requested source type(s). Closest matching signals:\n"
                f"{bullets}"
            )
        else:
            response = "No relevant signals were found for the requested source type(s)."
        return {
            "response": response,
            "conversationId": result.get("conversationId"),
            "citations": visible,
            "trimmed": [],
            "source": "retrieval-only",
            "matched": None,
            "tool": None,
        }
    except Exception:
        return result


def _is_allowed_origin(origin: str | None) -> bool:
    """Allow local-dev browser origins on any localhost port."""
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return parsed.hostname in {"127.0.0.1", "localhost"}


def _resolve_scenario_path(raw_scenario: str) -> Path:
    """Resolve scenario path as absolute, relative to repo root, or relative to simulator/."""
    p = Path(raw_scenario)
    if p.is_absolute():
        return p
    repo_root = Path(__file__).resolve().parent
    from_repo = repo_root / p
    if from_repo.exists():
        return from_repo
    return repo_root / "simulator" / p


def _resolve_mcp_command(raw_command: str) -> str:
    """Resolve MCP command path and fail-safe to current interpreter if moved."""
    cmd = (raw_command or "").strip()
    if not cmd:
        raise ValueError("Missing required environment variable: WORKIQ_MCP_COMMAND")
    if not any(sep in cmd for sep in ("\\", "/", ":")):
        return cmd
    p = Path(cmd)
    if p.exists():
        return str(p)
    return sys.executable


def _load_personas_for_scenario(scenario_path: Path) -> list:
    """Load persona metadata from scenario personas.json if present."""
    personas_file = scenario_path / "personas.json"
    if not personas_file.exists():
        return []
    try:
        with open(personas_file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        personas = payload.get("personas", []) if isinstance(payload, dict) else []
        return [p for p in personas if isinstance(p, dict) and p.get("id")]
    except Exception:
        return []


def _get_required_env(name: str) -> str:
    """Return a required env var value or raise a helpful error."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _init_mcp_tool(persona: str):
    """Initialize the MCP stdio tool with the given persona."""
    from agent_framework import MCPStdioTool

    mcp_command = _resolve_mcp_command(_get_required_env("WORKIQ_MCP_COMMAND"))
    mcp_args = shlex.split(os.getenv("WORKIQ_MCP_ARGS", ""), posix=False)
    scenario = os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c6-edkh")

    return MCPStdioTool(
        name="workiq-mcp",
        command=mcp_command,
        args=mcp_args,
        env={
            **os.environ,
            "WORKIQ_SIM_PERSONA": persona,
            "WORKIQ_SIM_SCENARIO": scenario,
        },
    )


def _init_a2a_tool(persona: str):
    """Initialize the A2A tool with custom persona header."""
    from agent_framework_a2a import A2AAgent
    import httpx

    a2a_url = os.getenv("WORKIQ_A2A_URL", "http://127.0.0.1:8920")
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0),
        headers={"X-WorkIQ-Persona": persona},
    )
    a2a_agent = A2AAgent(url=a2a_url, http_client=http_client)
    return a2a_agent.as_tool(
        name="workiq-ask",
        description="Ask Work IQ a question about the Atlas payments incident. Returns a cited answer grounded in work context.",
    )


def init_app():
    """Initialize the shared OpenAI client and event loop on app startup."""
    global _client, event_loop, available_personas, sim_engine, sim_scenario
    try:
        # Create a persistent event loop for all async operations
        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)

        # Load available personas from scenario
        raw_scenario = os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c6-edkh")
        scenario_path = _resolve_scenario_path(raw_scenario)
        available_personas = _load_personas_for_scenario(scenario_path)

        # Load simulator engine for citation resolution (even in LLM mode)
        simulator_dir = Path(__file__).resolve().parent / "simulator"
        if str(simulator_dir) not in sys.path:
            sys.path.insert(0, str(simulator_dir))
        import engine as sim_engine_module
        sim_scenario = sim_engine_module.load_scenario(str(scenario_path))
        sim_engine = sim_engine_module

        # Setup Azure OpenAI client 
        endpoint = _get_required_env("WORKIQ_AZURE_ENDPOINT")
        model = os.getenv("WORKIQ_MODEL", "gpt-5-mini")
        api_version = os.getenv("WORKIQ_AZURE_API_VERSION", "2024-08-01-preview")

        _client = OpenAIChatCompletionClient(
            model=model,
            credential=DefaultAzureCredential(),
            azure_endpoint=endpoint,
            api_version=api_version,
        )

        # Initialize data connectors
        _init_connectors()

        return True
    except Exception as e:
        print(f"Failed to initialize app: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def _init_connectors():
    """Initialize data connectors for multi-source queries."""
    try:
        manager = get_connector_manager()
        endpoint = os.getenv("WORKIQ_AZURE_ENDPOINT", "").strip()
        if endpoint and "YOUR-RESOURCE" not in endpoint.upper():
            msgraph_config = ConnectorConfig(
                connector_id="msgraph_primary",
                connector_type=ConnectorType.MSGRAPH,
                enabled=True,
                auth_config={
                    "tenant_id": os.getenv("WORKIQ_AZURE_TENANT", ""),
                    "client_id": os.getenv("WORKIQ_AZURE_CLIENT_ID", ""),
                    "client_secret": os.getenv("WORKIQ_AZURE_CLIENT_SECRET", ""),
                },
            )
            msgraph = MSGraphConnector(msgraph_config)
            manager.register_connector(msgraph)

        config_path = Path(__file__).resolve().parent / "connectors" / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config_data = json.load(f)
                config_json = json.dumps(config_data)
                for key, value in os.environ.items():
                    config_json = config_json.replace(f"${{{key}}}", value)
                config_data = json.loads(config_json)
                for connector_config in config_data.get("connectors", []):
                    if not connector_config.get("enabled", True):
                        continue
                    conn_type = connector_config.get("type")
                    conn_id = connector_config.get("id")
                    if conn_type == "msgraph":
                        config = ConnectorConfig(
                            connector_id=conn_id,
                            connector_type=ConnectorType.MSGRAPH,
                            enabled=True,
                            auth_config=connector_config.get("auth"),
                        )
                        manager.register_connector(MSGraphConnector(config))
                    elif conn_type == "custom_api":
                        config = ConnectorConfig(
                            connector_id=conn_id,
                            connector_type=ConnectorType.CUSTOM_API,
                            enabled=True,
                            auth_config=connector_config.get("auth"),
                            custom_config=connector_config.get("config"),
                        )
                        manager.register_connector(CustomAPIConnector(config))
            except Exception as e:
                print(f"Warning: Could not load connector config: {e}", file=sys.stderr)

        print(f"[OK] Initialized {len(manager.list_connectors())} connectors", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Connector initialization failed: {e}", file=sys.stderr)


def _create_agent_for_request(transport: str, persona: str):
    """Create an agent+tool for the given transport and persona (per-request)."""
    instructions = """You are a Work IQ assistant that answers questions about work context using the available tools.

MANDATORY RULES — you MUST follow ALL of these:

1. Make EXACTLY ONE tool call per user message. Never split, decompose, or break the user's question into multiple tool calls. Even if the question is compound (asks about multiple topics), send it as ONE single tool call.

2. Pass the user's EXACT question text as the tool input — character for character. Do NOT rephrase, summarize, shorten, elaborate, or paraphrase in any way.

3. After receiving the tool's single response, format it for the user. Do NOT call the tool again.

RESPONSE FORMAT (follow exactly):
- Start with a concise summary paragraph of the key decision or finding.
- List any actions or items as bullet points: "- [Action ID]: [Description], assigned to [Owner], due by [Time]."
- Do NOT add filler like "let me know if you need more details".
- Do NOT include citation IDs, links, or URLs anywhere in the answer body.
- Do NOT invent or add information that was not in the tool's response. Use ONLY what the tool returned.
- After the answer, add one blank line, then a "Citations:" section.
- Each citation on its own line: [ID]: "Short title" (e.g. [MTG-001]: "Meeting: Atlas Incident Bridge Call #2 (2026-06-11)").
- If the tool response already includes a Citations section, copy those citations exactly.
- Use only the citation's title — never paste full content. Citations appear ONLY in this section."""

    if transport == "mcp":
        tool = _init_mcp_tool(persona)
        agent = Agent(
            client=_client,
            name="WorkIQAgent-MCP",
            instructions=instructions,
            tools=[tool],
        )
    else:
        tool = _init_a2a_tool(persona)
        agent = Agent(
            client=_client,
            name="WorkIQAgent-A2A",
            instructions=instructions,
            tools=[tool],
        )

    return agent, tool


@app.before_request
def before_request():
    """Initialize session if needed."""
    if "conversation_id" not in session:
        session["conversation_id"] = str(datetime.now().timestamp())
    if "persona_id" not in session:
        session["persona_id"] = os.getenv("WORKIQ_SIM_PERSONA", "oncall_lead")


@app.after_request
def add_cors_headers(response):
    """Allow local browser UIs (e.g., Live Server) to call Flask API routes."""
    origin = request.headers.get("Origin")
    if _is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


@app.route("/")
def index():
    """Serve the main chat interface directly (bypass Jinja2 to avoid truncation)."""
    html_path = os.path.join(os.path.dirname(__file__), 'templates', 'index.html')
    return send_file(html_path, mimetype='text/html')


@app.route("/flyout-panel", methods=["GET"])
def flyout_panel():
    """Serve the side panel content (loaded dynamically)."""
    panel_path = os.path.join(os.path.dirname(__file__), 'templates', 'flyout-panel.html')
    if os.path.exists(panel_path):
        return send_file(panel_path, mimetype='text/html')
    return "", 204


@app.route("/api/personas", methods=["GET", "OPTIONS"])
def get_personas():
    """Return available simulator personas and the active selection."""
    personas = [
        {
            "id": p.get("id"),
            "label": p.get("label") or p.get("id"),
            "role": p.get("role") or "",
        }
        for p in available_personas
    ]
    return jsonify({
        "success": True,
        "personas": personas,
        "active_persona": session.get("persona_id", "all"),
    })


@app.route("/api/persona", methods=["POST", "OPTIONS"])
def set_persona():
    """Set active simulator persona for this browser session."""
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    requested = str(data.get("persona", "")).strip()
    if not requested:
        return jsonify({"success": False, "error": "Missing persona"}), 400

    valid_personas = {"all"} | {p.get("id") for p in available_personas if p.get("id")}
    if requested not in valid_personas:
        return jsonify({
            "success": False,
            "error": f"Unknown persona '{requested}'",
            "valid": sorted(valid_personas),
        }), 400

    session["persona_id"] = requested
    return jsonify({"success": True, "active_persona": requested})


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    """Handle chat messages via API."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)

        data = request.get_json(silent=True) or {}
        user_message = data.get("message", "").strip()
        transport = (data.get("transport") or "").lower()
        data_filters = data.get("data_filters")

        if not user_message:
            return jsonify({"error": "Empty message"}), 400

        if transport not in ("mcp", "a2a"):
            return jsonify({"error": "Missing or invalid 'transport'. Must be 'mcp' or 'a2a'."}), 400

        if not _client or not event_loop:
            return jsonify({"error": "App not initialized"}), 500

        active_persona = session.get("persona_id", "oncall_lead")
        print(f"[chat] Transport: {transport.upper()} | Persona: {active_persona} | Message: {user_message}")

        # Create agent+tool per-request with the active persona
        try:
            selected_agent, selected_tool = _create_agent_for_request(transport, active_persona)
        except Exception as e:
            return jsonify({"error": f"Failed to initialize {transport} agent: {str(e)}"}), 500

        # Run the async agent call using the persistent event loop
        async def run_agent():
            if transport == "mcp":
                async with selected_tool:
                    response = await selected_agent.run(user_message)
            else:
                response = await selected_agent.run(user_message)
            return response

        response = event_loop.run_until_complete(run_agent())

        # Extract the actual response text from AgentResponse object
        response_text = str(response) if response else ""

        # Extract token usage information from response
        token_usage = _extract_token_usage(response)
        if token_usage.get('total_tokens', 0) == 0 and response_text:
            estimated_completion = len(response_text) // 4
            estimated_prompt = len(user_message) // 4
            token_usage = {
                'prompt_tokens': max(1, estimated_prompt),
                'completion_tokens': max(1, estimated_completion),
                'total_tokens': max(1, estimated_prompt + estimated_completion),
            }

        # Parse citations from LLM text into structured format for the UI
        body, citations = _parse_citations_from_text(response_text)

        # Fallback: extract citation IDs from text and resolve via simulator engine
        if not citations and response_text and sim_engine and sim_scenario:
            try:
                citation_ids = _extract_citation_ids_from_text(response_text)
                if citation_ids:
                    persona_id = None if (active_persona or "").lower() == "all" else active_persona
                    resolved, _ = sim_engine.resolve_citations(sim_scenario, citation_ids, persona_id=persona_id)
                    citations = resolved
            except Exception:
                pass

        trace = _build_trace(user_message, active_persona, transport, citations, token_usage)

        return jsonify({
            "success": True,
            "response": body,
            "citations": citations,
            "trace": trace,
            "transport": transport,
            "active_persona": active_persona,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        print(f"Error in chat endpoint: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"Error processing message: {str(e)}"
        }), 500


@app.route("/api/clear", methods=["POST", "OPTIONS"])
def clear_history():
    """Clear the conversation history."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify({"success": True, "message": "Ready for new conversation"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def status():
    """Get agent status."""
    if _client and event_loop:
        configured_endpoint = os.getenv("WORKIQ_AZURE_ENDPOINT", "")
        configured_model = os.getenv("WORKIQ_MODEL", "gpt-5-mini")

        info = {
            "status": "ready",
            "model": configured_model,
            "endpoint": configured_endpoint,
            "scenario": os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c6-edkh"),
            "active_persona": session.get("persona_id", "oncall_lead"),
            "supported_transports": ["mcp", "a2a"],
            "a2a_server": os.getenv("WORKIQ_A2A_URL", "http://127.0.0.1:8920"),
        }

        return jsonify(info)
    else:
        return jsonify({
            "status": "not_initialized",
            "error": "App not initialized"
        }), 500


# ===== Data Connector Endpoints =====

@app.route("/api/connectors", methods=["GET", "OPTIONS"])
def list_connectors():
    """List all available data connectors."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        manager = get_connector_manager()
        connectors = manager.list_connectors(
            include_disabled=request.args.get("include_disabled", "false").lower() == "true"
        )
        return jsonify({"success": True, "connectors": connectors, "total": len(connectors)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/<connector_id>/status", methods=["GET", "OPTIONS"])
def connector_status(connector_id):
    """Get status of a specific connector."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        manager = get_connector_manager()
        connector = manager.get_connector(connector_id)
        if not connector:
            return jsonify({"success": False, "error": f"Connector not found: {connector_id}"}), 404
        return jsonify({"success": True, "status": connector.health_check()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/<connector_id>/authenticate", methods=["POST", "OPTIONS"])
def authenticate_connector(connector_id):
    """Authenticate a specific connector."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        manager = get_connector_manager()
        data = request.get_json() or {}
        credentials = data.get("credentials")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(manager.authenticate_connector(connector_id, credentials))
        return jsonify({"success": result, "connector_id": connector_id, "authenticated": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/fetch", methods=["POST", "OPTIONS"])
def fetch_from_connectors():
    """Fetch resources from one or more connectors."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json() or {}
        resource_type = data.get("resource_type")
        if not resource_type:
            return jsonify({"success": False, "error": "resource_type required"}), 400
        manager = get_connector_manager()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        responses = loop.run_until_complete(
            manager.fetch_resource_from_all(
                resource_type=resource_type,
                connector_ids=data.get("connector_ids"),
                filters=data.get("filters"),
                skip=data.get("skip", 0),
                top=data.get("top", 100),
            )
        )
        return jsonify({
            "success": True,
            "resource_type": resource_type,
            "results": [r.to_dict() for r in responses],
            "total_sources": len(responses),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/search", methods=["POST", "OPTIONS"])
def search_connectors():
    """Search across multiple connectors."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json() or {}
        query = data.get("query")
        if not query:
            return jsonify({"success": False, "error": "query required"}), 400
        manager = get_connector_manager()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        responses = loop.run_until_complete(
            manager.search(
                query=query,
                resource_types=data.get("resource_types"),
                connector_ids=data.get("connector_ids"),
                skip=data.get("skip", 0),
                top=data.get("top", 50),
            )
        )
        return jsonify({
            "success": True,
            "query": query,
            "results": [r.to_dict() for r in responses],
            "total_sources": len(responses),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/create-custom", methods=["POST", "OPTIONS"])
def create_custom_connector():
    """Create a new custom connector."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json() or {}
        connector_name = data.get("connector_name", "").strip()
        api_url = data.get("api_url", "").strip()
        auth_type = data.get("auth_type", "api_key").lower()
        if not connector_name:
            return jsonify({"success": False, "error": "connector_name is required"}), 400
        if not api_url:
            return jsonify({"success": False, "error": "api_url is required"}), 400
        connector_id = connector_name.lower().replace(" ", "_").replace("-", "_")
        connector_id = "".join(c for c in connector_id if c.isalnum() or c == "_")
        config = ConnectorConfig(
            connector_id=connector_id,
            connector_type=ConnectorType.CUSTOM_API,
            auth_config={"type": auth_type},
            custom_config={"base_url": api_url, "description": data.get("description", "")},
        )
        manager = get_connector_manager()
        manager.register_connector(CustomAPIConnector(config=config))
        return jsonify({
            "success": True,
            "connector_id": connector_id,
            "connector_name": connector_name,
            "message": f"Custom connector '{connector_name}' created successfully",
        }), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ===== Panel Orchestrator & Feature Access =====

_FEATURE_ACCESS = {
    "executive_brief": {"all", "oncall_lead", "incident_commander"},
    "progress_tracking": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "next_steps": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "timeline": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "data_filters": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "faqs": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "suggestions": {"all", "oncall_lead", "incident_commander"},
    "advanced_analytics": {"all", "incident_commander"},
    "risk_assessment": {"all", "oncall_lead", "incident_commander"},
    "compliance_reporting": {"all", "incident_commander"},
    "action_recommendations": {"all", "oncall_lead", "sre_engineer", "incident_commander"},
    "scenario_timeline": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "whatif_simulation": {"all", "oncall_lead", "sre_engineer", "incident_commander"},
    "premortem_generator": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "interactive_dashboard": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
}

_PERSONA_MAP = {
    "all": "all",
    "admin": "all",
    "oncall_lead": "oncall_lead",
    "sre_engineer": "sre_engineer",
    "contractor": "contractor",
    "incident_commander": "incident_commander",
    "Marco Reyes — On-Call Lead / SRE Lead": "oncall_lead",
    "Aisha Khan — SRE Engineer (on-call)": "sre_engineer",
    "Evan Cole — Contractor SRE (least privilege)": "contractor",
    "Helen Cho — Incident Commander / Director (escalation)": "incident_commander",
}


def _normalize_persona_id(persona_id: str | None) -> str:
    raw = (persona_id or "all").strip()
    mapped = _PERSONA_MAP.get(raw)
    if mapped:
        return mapped
    return raw.lower().replace(" ", "_").replace("-", "_")


def _can_access_feature(feature_name: str, persona_id: str | None) -> bool:
    key = (feature_name or "").lower().replace(" ", "_").replace("-", "_")
    allowed = _FEATURE_ACCESS.get(key, set())
    if not allowed:
        return False
    if "all" in allowed:
        return True
    return _normalize_persona_id(persona_id) in allowed


def _scenario_name() -> str:
    if sim_scenario is not None:
        root = getattr(sim_scenario, "root", None)
        if root is not None:
            name = getattr(root, "name", "")
            if name:
                return str(name)
    return "unknown"


def _generate_suggestions(sc_name: str) -> list[dict]:
    suggestions = {
        "c6-edkh": ["What are open action items?", "Show on-call escalations", "List pending owner reviews"],
        "c1-northbridge": ["What are the pending CAPA items?", "Show capacity planning status", "List open improvement actions"],
        "c2-contoso": ["What is blocking qualification?", "Who owns PPAP plan?", "Show OneNote recovery log summary"],
    }.get(sc_name, ["What is the current status?", "Show key action items", "List recent decisions"])
    return [{"label": s} for s in suggestions]


def _generate_timeline(conversation_history: list | None = None) -> list[dict]:
    timeline = [{"timestamp": datetime.now().isoformat(), "label": "Session started", "type": "session", "icon": "🚀"}]
    for item in (conversation_history or [])[:5]:
        if isinstance(item, dict):
            role = item.get("role", "user")
            content = str(item.get("content", "")).strip()
            if content:
                timeline.append({"timestamp": datetime.now().isoformat(), "label": f"{role.title()}: {content[:40]}...", "type": "message", "icon": "💬"})
    return timeline[:8]


def _generate_nextsteps(sc_name: str, last_response: str | None = None) -> list[dict]:
    base = [
        {"label": "Draft response", "icon": "✍️", "priority": "medium"},
        {"label": "Set reminder", "icon": "⏰", "priority": "low"},
        {"label": "Review sources", "icon": "📚", "priority": "medium"},
    ]
    if (last_response or "").lower().find("owner") >= 0:
        base.insert(0, {"label": "Verify ownership", "icon": "👤", "priority": "high"})
    return base[:5]


def _generate_progress(response_count: int = 0, citations: list | None = None) -> dict:
    kinds = {(c or {}).get("kind") for c in (citations or []) if isinstance(c, dict)}
    source_map = {"email": "Emails", "meeting": "Meetings", "teams_message": "Teams", "file": "Files", "onenote_page": "OneNote", "milestone": "Tables", "capa": "Tables"}
    source_categories = sorted({source_map[k] for k in kinds if k in source_map})
    coverage_percent = min(100, int((len(source_categories) / 6) * 100)) if source_categories else 0
    return {
        "response_count": response_count,
        "sources_used": source_categories,
        "coverage_percent": coverage_percent,
        "depth_score": min(10, (response_count * 2) + len(source_categories)),
        "citations_count": len(citations or []),
        "status": "active",
    }


@app.route("/api/agent/orchestrate", methods=["POST", "OPTIONS"])
def orchestrate_agents():
    """Orchestrate all panel agents — called on page load."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        sc_name = _scenario_name()
        return jsonify({
            "success": True,
            "suggestions": _generate_suggestions(sc_name),
            "timeline": _generate_timeline([]),
            "nextsteps": _generate_nextsteps(sc_name, None),
            "progress": _generate_progress(0, []),
        })
    except Exception as e:
        print(f"[ORCHESTRATOR] Error: {e}", file=sys.stderr)
        return jsonify({"success": False, "error": str(e), "suggestions": [], "timeline": [], "nextsteps": [], "progress": {}}), 500


@app.route("/api/agent/timeline", methods=["POST", "OPTIONS"])
def agent_timeline():
    """Generate timeline after messages are processed."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json(silent=True) or {}
        timeline = _generate_timeline(data.get("conversation_history", []))
        return jsonify({"success": True, "timeline": timeline})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "timeline": []}), 500


@app.route("/api/agent/nextsteps", methods=["POST", "OPTIONS"])
def agent_nextsteps():
    """Generate next steps after a response."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json(silent=True) or {}
        nextsteps = _generate_nextsteps(_scenario_name(), data.get("last_response"))
        return jsonify({"success": True, "nextsteps": nextsteps})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "nextsteps": []}), 500


def _generate_exec_brief(sc_name: str) -> dict:
    summary = {
        "c2-contoso": "Contoso milestone qualification on track. Key stakeholder alignment achieved.",
        "c6-edkh": "EDKH platform stabilizing. On-call operations nominal and action tracking improving.",
    }.get(sc_name, f"Status update for {sc_name}. Monitoring key metrics and progress.")
    return {
        "summary": summary,
        "risks": [{"level": "medium", "description": "General project risks under review"}],
        "blockers": [{"description": "Stakeholder approvals pending", "owner": "TBD", "due": "2026-07-15"}],
        "next_actions": [{"action": "Review project status", "owner": "Project Manager", "due": "2026-07-10", "priority": "medium"}],
        "overall_health": "Healthy",
        "timestamp": datetime.now().isoformat(),
    }


def _generate_action_recommendations(sc_name: str) -> dict:
    today = datetime.now()
    actions = [
        {
            "action": "Review pending items",
            "description": "Assess all pending work items and prioritize next steps",
            "owner": "Team Lead",
            "owner_role": "Manager",
            "due_date": (today + timedelta(days=7)).isoformat(),
            "priority": "medium",
            "category": "General",
            "status": "pending",
        },
        {
            "action": "Schedule stakeholder sync",
            "description": "Align on priorities and resource needs with stakeholders",
            "owner": "Project Manager",
            "owner_role": "Coordinator",
            "due_date": (today + timedelta(days=3)).isoformat(),
            "priority": "high",
            "category": "Communication",
            "status": "pending",
        },
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "context": "Scenario-aligned recommended actions",
        "actions": actions,
        "total_actions": len(actions),
        "critical_count": 0,
        "high_count": 1,
        "timestamp": datetime.now().isoformat(),
    }


def _generate_scenario_timeline(sc_name: str) -> dict:
    events = [
        {"timestamp": "2026-07-06T14:30:00Z", "category": "Alert", "actor": "Monitoring System", "title": "Issue Detection", "description": "Alert fired for high resource usage", "severity": "high"},
        {"timestamp": "2026-07-06T14:45:00Z", "category": "Response", "actor": "On-call Engineer", "title": "Investigation Started", "description": "Root cause analysis initiated", "severity": "medium"},
        {"timestamp": "2026-07-06T15:00:00Z", "category": "Resolution", "actor": "Operations", "title": "Service Stabilized", "description": "Mitigation applied and service health restored", "severity": "low"},
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "scenario_display": f"{sc_name} Timeline",
        "context": "Chronological reconstruction of key events",
        "events": events,
        "total_events": len(events),
        "critical_count": 0,
        "high_count": 1,
        "duration": "~30 minutes",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _generate_whatif_simulation(sc_name: str) -> dict:
    scenarios = [
        {"name": "Optimistic Path", "description": "Best case with no new blockers", "probability": 0.4, "impact": "No delay", "adjusted_timeline": "On Schedule", "risk_level": "low", "affected_milestones": 0},
        {"name": "Expected Path", "description": "Minor dependency delays", "probability": 0.45, "impact": "1-week delay", "adjusted_timeline": "+7 days", "risk_level": "medium", "affected_milestones": 1},
        {"name": "Pessimistic Path", "description": "Major issue in critical path", "probability": 0.15, "impact": "3-week delay", "adjusted_timeline": "+21 days", "risk_level": "high", "affected_milestones": 2},
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "scenario_display": f"{sc_name} What-If",
        "baseline_timeline": "Current baseline",
        "baseline_milestones": [{"name": "Milestone 1", "date": "2026-07-15", "status": "Planned"}],
        "scenarios": scenarios,
        "total_scenarios": len(scenarios),
        "weighted_risk_delay_days": 6,
        "recommendation": "Expected delay: ~6 days. Monitor critical path milestones.",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _generate_premortem(sc_name: str, persona_id: str) -> dict:
    return {
        "scenario_display": f"{sc_name} Reliability Program",
        "active_milestone": "Upcoming Milestone",
        "target_date": "2026-07-31",
        "risk_window_days": 14,
        "risk_score": 1.4,
        "highest_risk_mode": "Dependency delay",
        "failure_modes": [
            {"name": "Dependency delay", "probability": 0.3, "impact": "medium", "early_signal": "Critical dependencies remain unconfirmed", "blast_radius": "Milestone date likely to slip"},
        ],
        "preventive_actions": [
            {"action": "Set contingency owner and fallback plan", "owner": "Program Manager", "due": "2026-07-10", "priority": "high"},
        ],
        "recommendation": "Execute high-priority preventive actions within 48 hours and verify early signals daily.",
        "generated_for_persona": persona_id or "all",
        "timestamp": datetime.now().isoformat(),
    }


def _generate_progress_tracking(sc_name: str) -> dict:
    points = [
        {"day": "Day 1", "value": 50, "status": "flat", "incidents": 2},
        {"day": "Day 2", "value": 55, "status": "improving", "incidents": 1},
        {"day": "Day 3", "value": 60, "status": "improving", "incidents": 1},
        {"day": "Day 4", "value": 65, "status": "improving", "incidents": 1},
        {"day": "Day 5", "value": 70, "status": "improving", "incidents": 0},
        {"day": "Day 6", "value": 75, "status": "improving", "incidents": 0},
        {"day": "Day 7", "value": 80, "status": "improving", "incidents": 0},
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "scenario_display": f"{sc_name} Progress",
        "trend_label": "Activity Trend",
        "data_points": points,
        "summary": "Activity trending upward with improving engagement metrics.",
        "activities": ["Initial analysis", "Planning phase", "Execution started", "Progress monitoring"],
        "trend_direction": "upward",
        "trend_percentage": 60,
        "total_incidents": 5,
        "avg_daily_incidents": 1,
        "current_value": 80,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _generate_interactive_dashboard(sc_name: str) -> dict:
    kpis = [
        {"label": "Overall Progress", "value": "72%", "target": "80%", "status": "warning"},
        {"label": "Critical Issues", "value": "0", "target": "0", "status": "success"},
        {"label": "Team Alignment", "value": "85%", "target": ">80%", "status": "success"},
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "scenario_display": f"{sc_name} Dashboard",
        "health_status": "On Track",
        "health_color": "green",
        "kpis": kpis,
        "kpi_summary": {"total": len(kpis), "critical": 0, "warning": 1, "success": 2},
        "top_blockers": [{"title": "Generic blocker", "severity": "medium", "owner": "Team Lead", "age_days": 1}],
        "blocker_count": 1,
        "top_actions": [{"action": "Review metrics", "owner": "Manager", "due": "2026-07-10", "priority": "medium"}],
        "action_count": 1,
        "critical_action_count": 0,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.route("/api/feature-acl", methods=["GET", "OPTIONS"])
def feature_acl():
    """Return feature access control list for current persona."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        active_persona = session.get("persona_id", "all")
        normalized = _normalize_persona_id(active_persona)
        allowed_features = [feature for feature in _FEATURE_ACCESS if _can_access_feature(feature, active_persona)]
        acl_dict = {feature: _can_access_feature(feature, active_persona) for feature in _FEATURE_ACCESS}
        return jsonify({
            "success": True,
            "persona_id": normalized,
            "allowed_features": allowed_features,
            "acl": acl_dict,
        })
    except Exception as e:
        print(f"[FEATURE_ACL] Error: {e}", file=sys.stderr)
        return jsonify({"success": False, "error": str(e), "acl": {}}), 500


@app.route("/api/agent/progress-trend", methods=["POST", "OPTIONS"])
def agent_progress_trend():
    """Generate 7-day trend data for progress visualization."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        trend_values = [50, 55, 60, 65, 70, 75, 80]
        today = datetime.now()
        trend_data = [(today - timedelta(days=6 - i)).strftime('%Y-%m-%d') for i in range(7)]
        return jsonify({
            "success": True,
            "trend": trend_values,
            "trendDirection": "improving",
            "trendDescription": "↑ Trending up - Improved activity",
            "dates": trend_data,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "trend": []}), 500


@app.route("/api/agent/executive-brief", methods=["POST", "OPTIONS"])
def agent_executive_brief():
    """Generate executive brief."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        persona_id = session.get("persona_id", "all")
        if not _can_access_feature("executive_brief", persona_id):
            return jsonify({"success": False, "error": "Access denied for this persona"}), 403
        return jsonify({"success": True, **_generate_exec_brief(_scenario_name())})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/action-recommendations", methods=["POST", "OPTIONS"])
def agent_action_recommendations():
    """Generate action recommendations."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        persona_id = session.get("persona_id", "all")
        if not _can_access_feature("action_recommendations", persona_id):
            return jsonify({"success": False, "error": "Access denied for this persona"}), 403
        return jsonify(_generate_action_recommendations(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/scenario-timeline", methods=["POST", "OPTIONS"])
def agent_scenario_timeline():
    """Generate scenario timeline."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify(_generate_scenario_timeline(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/whatif-simulation", methods=["POST", "OPTIONS"])
def agent_whatif_simulation():
    """Generate what-if simulation."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        persona_id = session.get("persona_id", "all")
        if not _can_access_feature("whatif_simulation", persona_id):
            return jsonify({"success": False, "error": "Access denied for this persona"}), 403
        return jsonify(_generate_whatif_simulation(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/pre-mortem-generator", methods=["POST", "OPTIONS"])
def agent_premortem():
    """Generate pre-mortem analysis."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        persona_id = session.get("persona_id", "all")
        if not _can_access_feature("premortem_generator", persona_id):
            return jsonify({"success": False, "error": "Access denied for this persona"}), 403
        return jsonify({"success": True, **_generate_premortem(_scenario_name(), persona_id)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/progress-tracking", methods=["POST", "OPTIONS"])
def agent_progress_tracking():
    """Generate progress tracking data."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify(_generate_progress_tracking(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/interactive-dashboard", methods=["POST", "OPTIONS"])
def agent_interactive_dashboard():
    """Generate interactive dashboard data."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify(_generate_interactive_dashboard(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/<connector_id>/resources", methods=["GET", "OPTIONS"])
def get_connector_resources(connector_id):
    """Get supported resources for a connector."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        manager = get_connector_manager()
        connector = manager.get_connector(connector_id)
        if not connector:
            return jsonify({"success": False, "error": f"Connector not found: {connector_id}"}), 404
        return jsonify({
            "success": True,
            "connector_id": connector_id,
            "connector_name": connector.connector_name,
            "resources": connector.supported_resources,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    """Handle 500 errors."""
    return jsonify({"error": "Internal server error"}), 500


def main():
    """Main entry point."""
    print("⏳ Initializing Work IQ Agent Web UI...")

    port = int(os.getenv("WORKIQ_PORT", "5000"))

    if not init_app():
        print("\n Failed to initialize app. Please check your configuration.", file=sys.stderr)
        print("\nRequired environment variables:")
        print("  - WORKIQ_AZURE_ENDPOINT")
        print("\nFor MCP transport (initialized on first request):")
        print("  - WORKIQ_MCP_COMMAND")
        print("  - WORKIQ_MCP_ARGS")
        print("\nFor A2A transport (initialized on first request):")
        print("  - WORKIQ_A2A_URL (default: http://127.0.0.1:8920)")
        sys.exit(1)

    print("App initialized! Agents will be created on first request per transport.")
    print("\n Starting Web Server...")
    print(f"   Open your browser and go to: http://localhost:{port}")
    print("   Press CTRL+C to stop the server\n")

    # Run the Flask app
    app.run(
        host="127.0.0.1",
        port=port,
        debug=False,
        use_reloader=False
    )


if __name__ == "__main__":
    main()
"""
Unified Web UI for the Work IQ Agent using Flask.
Supports both MCP and A2A transports — controlled via the incoming request payload.

Request format:
    {"message": "...", "transport": "mcp"}   — uses MCP stdio tool
    {"message": "...", "transport": "a2a"}   — uses A2A protocol (default)
"""

import os
import asyncio
import sys
import shlex
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, session, send_file
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from agent_framework import Agent, Message
from agent_framework.openai import OpenAIChatCompletionClient

# Data Connector Framework
from connectors import (
    get_connector_manager,
    ConnectorConfig,
    ConnectorType,
    MSGraphConnector,
    CustomAPIConnector,
)

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your-secret-key-change-in-production")

# Shared state
_client = None
event_loop = None
available_personas = []
sim_engine = None
sim_scenario = None
last_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

# In-memory conversation history per session
_conversation_store: dict[str, list] = {}
_MAX_HISTORY_TURNS = 10  # keep last 10 user+assistant pairs


def _parse_citations_from_text(text: str) -> tuple[str, list]:
    """Parse a 'Citations:' section from the LLM response text.

    Returns (body_without_citations, structured_citations_list).
    Each citation is: {"citation_id": "MTG-001", "kind": "source", "title": "..."}.
    Handles various LLM formatting styles: with/without quotes, bullets, markdown bold, etc.
    """
    # Split on "Citations:" heading — tolerate markdown bold, bullets, varied whitespace
    parts = re.split(r'\n\s*\*{0,2}Citations:?\*{0,2}\s*\n?', text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2:
        # Fallback: try splitting on "Sources:" as some models use that heading
        parts = re.split(r'\n\s*\*{0,2}Sources:?\*{0,2}\s*\n?', text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2:
        return text.strip(), []

    body = parts[0].strip()
    citations_block = parts[1].strip()

    citations = []

    # Pattern 1: [ID]: "Title" or [ID]: "Title"
    for match in re.finditer(r'\[([A-Z]+-\d+)\]:\s*["\u201c]([^"\u201d]*)["\u201d]', citations_block):
        cit_id = match.group(1)
        title = match.group(2)
        citations.append({"citation_id": cit_id, "title": title})

    # Pattern 2: [ID]: Title (no quotes) — only if pattern 1 found nothing
    if not citations:
        for match in re.finditer(r'\[([A-Z]+-\d+)\]:\s*(.+)', citations_block):
            cit_id = match.group(1)
            title = match.group(2).strip().strip('"').strip('\u201c\u201d')
            citations.append({"citation_id": cit_id, "title": title})

    # Pattern 3: - ID: "Title" or - ID — Title (no brackets, with bullet)
    if not citations:
        for match in re.finditer(r'[-•*]\s*([A-Z]+-\d+)[:\s—–-]+\s*(.+)', citations_block):
            cit_id = match.group(1)
            title = match.group(2).strip().strip('"').strip('\u201c\u201d')
            citations.append({"citation_id": cit_id, "title": title})

    # Pattern 4: bare ID: Title (no brackets, no bullets)
    if not citations:
        for match in re.finditer(r'^([A-Z]+-\d+)[:\s—–-]+\s*(.+)', citations_block, re.MULTILINE):
            cit_id = match.group(1)
            title = match.group(2).strip().strip('"').strip('\u201c\u201d')
            citations.append({"citation_id": cit_id, "title": title})

    # Assign kind based on title or citation_id prefix
    for c in citations:
        title_lower = c["title"].lower()
        cid = c["citation_id"]
        if cid.startswith("MTG") or "meeting" in title_lower:
            c["kind"] = "meeting"
        elif cid.startswith("EML") or "email" in title_lower:
            c["kind"] = "email"
        elif cid.startswith("FILE") or "file" in title_lower or "doc" in title_lower:
            c["kind"] = "file"
        elif cid.startswith("MSG") or "teams" in title_lower or "channel" in title_lower:
            c["kind"] = "teams_message"
        elif cid.startswith("ONC") or "onenote" in title_lower:
            c["kind"] = "onenote_page"
        elif cid.startswith("ACT") or "action" in title_lower:
            c["kind"] = "meeting"
        else:
            c["kind"] = "source"

    return body, citations


def _build_trace(question: str, active_persona: str, transport: str, citations: list, token_usage: dict | None = None, is_write_action: bool = False) -> dict:
    """Build a trace payload for the UI flyout."""
    if token_usage is None:
        token_usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    fixture_map = {
        "email": "emails.json",
        "meeting": "meetings.json",
        "teams_message": "teams.json",
        "file": "files.json",
        "onenote_page": "onenote.json",
    }
    files_used = []
    seen = set()
    for c in citations:
        f = fixture_map.get(c.get("kind", ""), "tables/*.json")
        if f not in seen:
            seen.add(f)
            files_used.append(f)

    steps = [
        f"Received question over REST: {question[:120]}",
        f"Applied active persona: {active_persona}",
        f"Selected transport mode: {transport.upper()}",
        f"Execution path: agent+{transport}" + (" (write-action mode)" if is_write_action else ""),
    ]
    if is_write_action:
        steps.append("Detected write-action intent → multi-step tool orchestration enabled")
        steps.append("Step 1: ask_work_iq → gather context (open actions from bridge call)")
        steps.append("Step 2: fetch → check existing rows in action_tracker")
        steps.append("Step 3: create_entity / update_entity → apply changes")
        if "action_tracker" not in [f for f in files_used]:
            files_used.append("tables/action_tracker.json")
    if citations:
        steps.append(f"Resolved citations: {len(citations)}")
    else:
        steps.append("No citations resolved for this response")

    if token_usage.get('total_tokens', 0) > 0:
        total = token_usage['total_tokens']
        prompt = token_usage.get('prompt_tokens', 0)
        completion = token_usage.get('completion_tokens', 0)
        steps.append(f"Token consumption: {total} total ({prompt} prompt + {completion} completion)")

    return {
        "transport": transport.upper(),
        "mode": f"agent+{transport}",
        "active_persona": active_persona,
        "source": None,
        "matched": None,
        "files_used": files_used,
        "steps": steps,
        "token_usage": token_usage,
    }


def _fixture_for_kind(kind: str) -> str:
    mapping = {
        "email": "emails.json",
        "meeting": "meetings.json",
        "action_item": "meetings.json#action_items",
        "teams_message": "teams.json",
        "file": "files.json",
        "onenote_page": "onenote.json",
        "person": "people.json",
        "milestone": "tables/milestone_tracker.json",
        "capa": "tables/capa_tracker.json",
    }
    return mapping.get(kind, "tables/*.json")


def _extract_token_usage(response_obj) -> dict:
    """Extract token usage information from agent response."""
    global last_token_usage
    usage_info = {}
    try:
        if last_token_usage.get('total_tokens', 0) > 0:
            return last_token_usage.copy()
        if hasattr(response_obj, 'usage_details'):
            usage = response_obj.usage_details
            if usage and isinstance(usage, dict):
                usage_info['prompt_tokens'] = usage.get('input_token_count', 0) or usage.get('prompt_tokens', 0)
                usage_info['completion_tokens'] = usage.get('output_token_count', 0) or usage.get('completion_tokens', 0)
                usage_info['total_tokens'] = usage.get('total_token_count', 0) or usage.get('total_tokens', 0)
                if usage_info.get('total_tokens', 0) > 0:
                    return usage_info
        if hasattr(response_obj, 'usage'):
            usage = response_obj.usage
            if usage:
                if isinstance(usage, dict):
                    usage_info.update(usage)
                else:
                    usage_info['prompt_tokens'] = getattr(usage, 'prompt_tokens', 0)
                    usage_info['completion_tokens'] = getattr(usage, 'completion_tokens', 0)
                    usage_info['total_tokens'] = getattr(usage, 'total_tokens', 0)
    except Exception:
        pass
    result = {
        'prompt_tokens': usage_info.get('prompt_tokens', 0),
        'completion_tokens': usage_info.get('completion_tokens', 0),
        'total_tokens': usage_info.get('total_tokens', 0),
    }
    if result.get('total_tokens', 0) > 0:
        last_token_usage = result.copy()
    return result


def _extract_citation_ids_from_text(text: str) -> list[str]:
    """Extract citation ID patterns from response text like EML-003, MTG-001, ACT-002."""
    if not text:
        return []
    pattern = r'\b([A-Z]{2,4})-(\d{3,4})\b'
    matches = re.findall(pattern, text)
    seen = set()
    citation_ids = []
    for prefix, num in matches:
        cid = f"{prefix}-{num}"
        if cid not in seen:
            citation_ids.append(cid)
            seen.add(cid)
    return citation_ids


def _maybe_enforce_source_intent(sc, engine_module, question: str, persona_id, result: dict) -> dict:
    """If a source-specific question returns mismatched golden sources,
    re-answer via source-filtered retrieval to keep citations aligned with user intent."""
    try:
        detect_hints = getattr(engine_module, "_detect_source_hints", None)
        if not callable(detect_hints):
            return result
        hints = detect_hints(question) or set()
        if not hints:
            return result
        if result.get("source") != "golden":
            return result
        matched_id = result.get("matched")
        if not matched_id:
            return result
        golden_entry = next((g for g in sc.golden if g.get("id") == matched_id), None)
        if not golden_entry:
            return result
        cited_kinds = set()
        for cid in golden_entry.get("citations", []):
            entry = sc.index.get(cid)
            if entry is None:
                continue
            kind, _ = entry
            cited_kinds.add(kind)
        if cited_kinds & set(hints):
            return result
        all_snippets = engine_module._all_snippets(sc, persona_id)
        filter_by_hints = getattr(engine_module, "_filter_snippets_by_hints", None)
        if callable(filter_by_hints):
            all_snippets = filter_by_hints(sc, all_snippets, hints)
        top = engine_module._retrieve(all_snippets, question)
        cited_ids = [s.get("id") for s in top if s.get("id")]
        visible, _ = engine_module.resolve_citations(sc, cited_ids, persona_id)
        if top:
            bullets = "\n".join(f"- [{s['id']}] {s['text'][:140]}" for s in top)
            response = (
                "Answer constrained to requested source type(s). Closest matching signals:\n"
                f"{bullets}"
            )
        else:
            response = "No relevant signals were found for the requested source type(s)."
        return {
            "response": response,
            "conversationId": result.get("conversationId"),
            "citations": visible,
            "trimmed": [],
            "source": "retrieval-only",
            "matched": None,
            "tool": None,
        }
    except Exception:
        return result


def _is_allowed_origin(origin: str | None) -> bool:
    """Allow local-dev browser origins on any localhost port."""
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return parsed.hostname in {"127.0.0.1", "localhost"}


def _resolve_scenario_path(raw_scenario: str) -> Path:
    """Resolve scenario path as absolute, relative to repo root, or relative to simulator/."""
    p = Path(raw_scenario)
    if p.is_absolute():
        return p
    repo_root = Path(__file__).resolve().parent
    from_repo = repo_root / p
    if from_repo.exists():
        return from_repo
    return repo_root / "simulator" / p


def _resolve_mcp_command(raw_command: str) -> str:
    """Resolve MCP command path and fail-safe to current interpreter if moved."""
    cmd = (raw_command or "").strip()
    if not cmd:
        raise ValueError("Missing required environment variable: WORKIQ_MCP_COMMAND")
    if not any(sep in cmd for sep in ("\\", "/", ":")):
        return cmd
    p = Path(cmd)
    if p.exists():
        return str(p)
    return sys.executable


def _load_personas_for_scenario(scenario_path: Path) -> list:
    """Load persona metadata from scenario personas.json if present."""
    personas_file = scenario_path / "personas.json"
    if not personas_file.exists():
        return []
    try:
        with open(personas_file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        personas = payload.get("personas", []) if isinstance(payload, dict) else []
        return [p for p in personas if isinstance(p, dict) and p.get("id")]
    except Exception:
        return []


def _get_required_env(name: str) -> str:
    """Return a required env var value or raise a helpful error."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _init_mcp_tool(persona: str):
    """Initialize the MCP stdio tool with the given persona."""
    from agent_framework import MCPStdioTool

    mcp_command = _resolve_mcp_command(_get_required_env("WORKIQ_MCP_COMMAND"))
    mcp_args = shlex.split(os.getenv("WORKIQ_MCP_ARGS", ""), posix=False)
    scenario = os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c6-edkh")

    return MCPStdioTool(
        name="workiq-mcp",
        command=mcp_command,
        args=mcp_args,
        env={
            **os.environ,
            "WORKIQ_SIM_PERSONA": persona,
            "WORKIQ_SIM_SCENARIO": scenario,
        },
    )


def _init_a2a_tool(persona: str):
    """Initialize the A2A tool with custom persona header."""
    from agent_framework_a2a import A2AAgent
    import httpx

    a2a_url = os.getenv("WORKIQ_A2A_URL", "http://127.0.0.1:8920")
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0),
        headers={"X-WorkIQ-Persona": persona},
    )
    a2a_agent = A2AAgent(url=a2a_url, http_client=http_client)
    return a2a_agent.as_tool(
        name="workiq-ask",
        description="Ask Work IQ a question about the Atlas payments incident. Returns a cited answer grounded in work context.",
    )


def init_app():
    """Initialize the shared OpenAI client and event loop on app startup."""
    global _client, event_loop, available_personas, sim_engine, sim_scenario
    try:
        # Create a persistent event loop for all async operations
        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)

        # Load available personas from scenario
        raw_scenario = os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c6-edkh")
        scenario_path = _resolve_scenario_path(raw_scenario)
        available_personas = _load_personas_for_scenario(scenario_path)

        # Load simulator engine for citation resolution (even in LLM mode)
        simulator_dir = Path(__file__).resolve().parent / "simulator"
        if str(simulator_dir) not in sys.path:
            sys.path.insert(0, str(simulator_dir))
        import engine as sim_engine_module
        sim_scenario = sim_engine_module.load_scenario(str(scenario_path))
        sim_engine = sim_engine_module

        # Setup Azure OpenAI client 
        endpoint = _get_required_env("WORKIQ_AZURE_ENDPOINT")
        model = os.getenv("WORKIQ_MODEL", "gpt-5-mini")
        api_version = os.getenv("WORKIQ_AZURE_API_VERSION", "2024-08-01-preview")

        _client = OpenAIChatCompletionClient(
            model=model,
            credential=DefaultAzureCredential(),
            azure_endpoint=endpoint,
            api_version=api_version,
        )

        # Initialize data connectors
        _init_connectors()

        return True
    except Exception as e:
        print(f"Failed to initialize app: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def _init_connectors():
    """Initialize data connectors for multi-source queries."""
    try:
        manager = get_connector_manager()
        endpoint = os.getenv("WORKIQ_AZURE_ENDPOINT", "").strip()
        if endpoint and "YOUR-RESOURCE" not in endpoint.upper():
            msgraph_config = ConnectorConfig(
                connector_id="msgraph_primary",
                connector_type=ConnectorType.MSGRAPH,
                enabled=True,
                auth_config={
                    "tenant_id": os.getenv("WORKIQ_AZURE_TENANT", ""),
                    "client_id": os.getenv("WORKIQ_AZURE_CLIENT_ID", ""),
                    "client_secret": os.getenv("WORKIQ_AZURE_CLIENT_SECRET", ""),
                },
            )
            msgraph = MSGraphConnector(msgraph_config)
            manager.register_connector(msgraph)

        config_path = Path(__file__).resolve().parent / "connectors" / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config_data = json.load(f)
                config_json = json.dumps(config_data)
                for key, value in os.environ.items():
                    config_json = config_json.replace(f"${{{key}}}", value)
                config_data = json.loads(config_json)
                for connector_config in config_data.get("connectors", []):
                    if not connector_config.get("enabled", True):
                        continue
                    conn_type = connector_config.get("type")
                    conn_id = connector_config.get("id")
                    if conn_type == "msgraph":
                        config = ConnectorConfig(
                            connector_id=conn_id,
                            connector_type=ConnectorType.MSGRAPH,
                            enabled=True,
                            auth_config=connector_config.get("auth"),
                        )
                        manager.register_connector(MSGraphConnector(config))
                    elif conn_type == "custom_api":
                        config = ConnectorConfig(
                            connector_id=conn_id,
                            connector_type=ConnectorType.CUSTOM_API,
                            enabled=True,
                            auth_config=connector_config.get("auth"),
                            custom_config=connector_config.get("config"),
                        )
                        manager.register_connector(CustomAPIConnector(config))
            except Exception as e:
                print(f"Warning: Could not load connector config: {e}", file=sys.stderr)

        print(f"[OK] Initialized {len(manager.list_connectors())} connectors", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Connector initialization failed: {e}", file=sys.stderr)


def _is_write_action_request(message: str) -> bool:
    """Detect whether the user's message asks the agent to create or update entities."""
    m = message.lower()
    write_verbs = {"create", "update", "add", "insert", "modify", "patch", "set", "change", "open", "track"}
    target_nouns = {"action item", "action_item", "tracker", "incident tracker",
                    "action tracker", "entity", "row", "record", "milestone",
                    "work order", "table"}
    has_verb = any(v in m for v in write_verbs)
    has_noun = any(n in m for n in target_nouns)
    return has_verb and has_noun


_READ_ONLY_INSTRUCTIONS = """You are a Work IQ assistant that answers questions about work context using the available tools.

MANDATORY RULES — you MUST follow ALL of these:

1. Make EXACTLY ONE tool call per user message. Never split, decompose, or break the user's question into multiple tool calls. Even if the question is compound (asks about multiple topics), send it as ONE single tool call.

2. Pass the user's EXACT question text as the tool input — character for character. Do NOT rephrase, summarize, shorten, elaborate, or paraphrase in any way.

3. After receiving the tool's single response, format it for the user. Do NOT call the tool again.

RESPONSE FORMAT (follow exactly):
- Start with a concise summary paragraph of the key decision or finding.
- List any actions or items as bullet points: "- [Action ID]: [Description], assigned to [Owner], due by [Time]."
- Do NOT add filler like "let me know if you need more details".
- Do NOT include citation IDs, links, or URLs anywhere in the answer body.
- Do NOT invent or add information that was not in the tool's response. Use ONLY what the tool returned.
- After the answer, add one blank line, then a "Citations:" section.
- Each citation on its own line: [ID]: "Short title" (e.g. [MTG-001]: "Meeting: Atlas Incident Bridge Call #2 (2026-06-11)").
- If the tool response already includes a Citations section, copy those citations exactly.
- Use only the citation's title — never paste full content. Citations appear ONLY in this section."""


_WRITE_ACTION_INSTRUCTIONS = """You are a Work IQ assistant that can BOTH read work context AND take actions (create/update records in trackers).

You have access to these tools through the connected MCP server:
- ask_work_iq: Query Work IQ for information about people, meetings, emails, Teams chats, files, and OneNote pages.
- fetch: Read rows from a Work IQ tracker table (e.g. action_tracker, milestone_tracker).
- create_entity: Create a new row in a Work IQ tracker table.
- update_entity: Update an existing row in a Work IQ tracker table by id.

WORKFLOW for create/update requests — follow these steps IN ORDER:

Step 1 — GATHER CONTEXT: Call ask_work_iq with the user's question to understand what actions/items need to be created or updated. Parse the response to extract each action item's details (text, owner, service, due time, status).

Step 2 — CHECK EXISTING STATE: Call fetch on the target table (e.g. "action_tracker") to see what rows already exist. This prevents duplicates.

Step 3 — ACT: For each action item identified in Step 1:
  a) If a matching row already exists in the table (same action text or same id), call update_entity with the row's id and a patch containing any changed fields (owner, service, due, status).
  b) If no matching row exists, call create_entity with a full record: {"action": "...", "service": "...", "owner": "PPL-xxx", "status": "Open", "due": "ISO-datetime"}.

Step 4 — REPORT: Summarize what you did. For each item, state whether it was created or updated, and list the final field values.

RULES:
- Do NOT skip Step 2. Always check existing rows before creating to avoid duplicates.
- Use the EXACT owner ids (PPL-xxx format) from the ask_work_iq response.
- Preserve existing field values when updating — only patch fields that changed.
- Do NOT invent information not present in the ask_work_iq response.

RESPONSE FORMAT:
- Start with a summary of what was done (e.g. "Created 1 new action item and updated 2 existing items in the action tracker.").
- List each item as a bullet: "- [ACT-xxx]: [action text] — owner: [name], service: [service], due: [time], status: [status] (created/updated)."
- After the answer, add one blank line, then a "Citations:" section referencing the source meeting/email.
- Each citation on its own line: [ID]: "Short title"."""


def _create_agent_for_request(transport: str, persona: str, is_write_action: bool = False):
    """Create an agent+tool for the given transport and persona (per-request).

    When is_write_action is True, the agent gets multi-step instructions that allow it
    to read context via ask_work_iq, then act via fetch/create_entity/update_entity.
    """
    instructions = _WRITE_ACTION_INSTRUCTIONS if is_write_action else _READ_ONLY_INSTRUCTIONS

    if transport == "mcp":
        tool = _init_mcp_tool(persona)
        agent = Agent(
            client=_client,
            name="WorkIQAgent-MCP",
            instructions=instructions,
            tools=[tool],
        )
    else:
        tool = _init_a2a_tool(persona)
        agent = Agent(
            client=_client,
            name="WorkIQAgent-A2A",
            instructions=instructions,
            tools=[tool],
        )

    return agent, tool


@app.before_request
def before_request():
    """Initialize session if needed."""
    if "conversation_id" not in session:
        session["conversation_id"] = str(datetime.now().timestamp())
    if "persona_id" not in session:
        session["persona_id"] = os.getenv("WORKIQ_SIM_PERSONA", "oncall_lead")


@app.after_request
def add_cors_headers(response):
    """Allow local browser UIs (e.g., Live Server) to call Flask API routes."""
    origin = request.headers.get("Origin")
    if _is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


@app.route("/")
def index():
    """Serve the main chat interface directly (bypass Jinja2 to avoid truncation)."""
    html_path = os.path.join(os.path.dirname(__file__), 'templates', 'index.html')
    return send_file(html_path, mimetype='text/html')


@app.route("/flyout-panel", methods=["GET"])
def flyout_panel():
    """Serve the side panel content (loaded dynamically)."""
    panel_path = os.path.join(os.path.dirname(__file__), 'templates', 'flyout-panel.html')
    if os.path.exists(panel_path):
        return send_file(panel_path, mimetype='text/html')
    return "", 204


@app.route("/api/personas", methods=["GET", "OPTIONS"])
def get_personas():
    """Return available simulator personas and the active selection."""
    personas = [
        {
            "id": p.get("id"),
            "label": p.get("label") or p.get("id"),
            "role": p.get("role") or "",
        }
        for p in available_personas
    ]
    return jsonify({
        "success": True,
        "personas": personas,
        "active_persona": session.get("persona_id", "all"),
    })


@app.route("/api/persona", methods=["POST", "OPTIONS"])
def set_persona():
    """Set active simulator persona for this browser session."""
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    requested = str(data.get("persona", "")).strip()
    if not requested:
        return jsonify({"success": False, "error": "Missing persona"}), 400

    valid_personas = {"all"} | {p.get("id") for p in available_personas if p.get("id")}
    if requested not in valid_personas:
        return jsonify({
            "success": False,
            "error": f"Unknown persona '{requested}'",
            "valid": sorted(valid_personas),
        }), 400

    session["persona_id"] = requested
    return jsonify({"success": True, "active_persona": requested})


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    """Handle chat messages via API."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)

        data = request.get_json(silent=True) or {}
        user_message = data.get("message", "").strip()
        transport = (data.get("transport") or "").lower()
        data_filters = data.get("data_filters")

        if not user_message:
            return jsonify({"error": "Empty message"}), 400

        if transport not in ("mcp", "a2a"):
            return jsonify({"error": "Missing or invalid 'transport'. Must be 'mcp' or 'a2a'."}), 400

        if not _client or not event_loop:
            return jsonify({"error": "App not initialized"}), 500

        active_persona = session.get("persona_id", "oncall_lead")
        is_write = _is_write_action_request(user_message)
        print(f"[chat] Transport: {transport.upper()} | Persona: {active_persona} | Write: {is_write} | Message: {user_message}")

        # Retrieve conversation history for this session
        session_id = session.get("conversation_id", "default")
        history = _conversation_store.get(session_id, [])

        # Create agent+tool per-request with the active persona
        try:
            selected_agent, selected_tool = _create_agent_for_request(transport, active_persona, is_write_action=is_write)
        except Exception as e:
            return jsonify({"error": f"Failed to initialize {transport} agent: {str(e)}"}), 500

        # Build messages: prior history + current user message
        messages_for_agent = list(history) + [Message("user", [user_message])]

        # Run the async agent call using the persistent event loop
        async def run_agent():
            if transport == "mcp":
                async with selected_tool:
                    response = await selected_agent.run(messages_for_agent)
            else:
                response = await selected_agent.run(messages_for_agent)
            return response

        response = event_loop.run_until_complete(run_agent())

        # Extract the actual response text from AgentResponse object
        response_text = str(response) if response else ""

        # Extract token usage information from response
        token_usage = _extract_token_usage(response)
        if token_usage.get('total_tokens', 0) == 0 and response_text:
            estimated_completion = len(response_text) // 4
            estimated_prompt = len(user_message) // 4
            token_usage = {
                'prompt_tokens': max(1, estimated_prompt),
                'completion_tokens': max(1, estimated_completion),
                'total_tokens': max(1, estimated_prompt + estimated_completion),
            }

        # Parse citations from LLM text into structured format for the UI
        body, citations = _parse_citations_from_text(response_text)

        # Fallback: extract citation IDs from text and resolve via simulator engine
        if not citations and response_text and sim_engine and sim_scenario:
            try:
                citation_ids = _extract_citation_ids_from_text(response_text)
                if citation_ids:
                    persona_id = None if (active_persona or "").lower() == "all" else active_persona
                    resolved, _ = sim_engine.resolve_citations(sim_scenario, citation_ids, persona_id=persona_id)
                    citations = resolved
            except Exception:
                pass

        trace = _build_trace(user_message, active_persona, transport, citations, token_usage, is_write_action=is_write)

        # Save this turn into conversation history
        history.append(Message("user", [user_message]))
        history.append(Message("assistant", [body]))
        # Cap history to last N turns (each turn = 2 messages)
        if len(history) > _MAX_HISTORY_TURNS * 2:
            history = history[-_MAX_HISTORY_TURNS * 2:]
        _conversation_store[session_id] = history

        return jsonify({
            "success": True,
            "response": body,
            "citations": citations,
            "trace": trace,
            "transport": transport,
            "active_persona": active_persona,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        print(f"Error in chat endpoint: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"Error processing message: {str(e)}"
        }), 500


@app.route("/api/clear", methods=["POST", "OPTIONS"])
def clear_history():
    """Clear the conversation history."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        session_id = session.get("conversation_id", "default")
        _conversation_store.pop(session_id, None)
        return jsonify({"success": True, "message": "Ready for new conversation"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def status():
    """Get agent status."""
    if _client and event_loop:
        configured_endpoint = os.getenv("WORKIQ_AZURE_ENDPOINT", "")
        configured_model = os.getenv("WORKIQ_MODEL", "gpt-5-mini")

        info = {
            "status": "ready",
            "model": configured_model,
            "endpoint": configured_endpoint,
            "scenario": os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c6-edkh"),
            "active_persona": session.get("persona_id", "oncall_lead"),
            "supported_transports": ["mcp", "a2a"],
            "a2a_server": os.getenv("WORKIQ_A2A_URL", "http://127.0.0.1:8920"),
        }

        return jsonify(info)
    else:
        return jsonify({
            "status": "not_initialized",
            "error": "App not initialized"
        }), 500


# ===== Data Connector Endpoints =====

@app.route("/api/connectors", methods=["GET", "OPTIONS"])
def list_connectors():
    """List all available data connectors."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        manager = get_connector_manager()
        connectors = manager.list_connectors(
            include_disabled=request.args.get("include_disabled", "false").lower() == "true"
        )
        return jsonify({"success": True, "connectors": connectors, "total": len(connectors)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/<connector_id>/status", methods=["GET", "OPTIONS"])
def connector_status(connector_id):
    """Get status of a specific connector."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        manager = get_connector_manager()
        connector = manager.get_connector(connector_id)
        if not connector:
            return jsonify({"success": False, "error": f"Connector not found: {connector_id}"}), 404
        return jsonify({"success": True, "status": connector.health_check()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/<connector_id>/authenticate", methods=["POST", "OPTIONS"])
def authenticate_connector(connector_id):
    """Authenticate a specific connector."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        manager = get_connector_manager()
        data = request.get_json() or {}
        credentials = data.get("credentials")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(manager.authenticate_connector(connector_id, credentials))
        return jsonify({"success": result, "connector_id": connector_id, "authenticated": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/fetch", methods=["POST", "OPTIONS"])
def fetch_from_connectors():
    """Fetch resources from one or more connectors."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json() or {}
        resource_type = data.get("resource_type")
        if not resource_type:
            return jsonify({"success": False, "error": "resource_type required"}), 400
        manager = get_connector_manager()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        responses = loop.run_until_complete(
            manager.fetch_resource_from_all(
                resource_type=resource_type,
                connector_ids=data.get("connector_ids"),
                filters=data.get("filters"),
                skip=data.get("skip", 0),
                top=data.get("top", 100),
            )
        )
        return jsonify({
            "success": True,
            "resource_type": resource_type,
            "results": [r.to_dict() for r in responses],
            "total_sources": len(responses),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/search", methods=["POST", "OPTIONS"])
def search_connectors():
    """Search across multiple connectors."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json() or {}
        query = data.get("query")
        if not query:
            return jsonify({"success": False, "error": "query required"}), 400
        manager = get_connector_manager()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        responses = loop.run_until_complete(
            manager.search(
                query=query,
                resource_types=data.get("resource_types"),
                connector_ids=data.get("connector_ids"),
                skip=data.get("skip", 0),
                top=data.get("top", 50),
            )
        )
        return jsonify({
            "success": True,
            "query": query,
            "results": [r.to_dict() for r in responses],
            "total_sources": len(responses),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/create-custom", methods=["POST", "OPTIONS"])
def create_custom_connector():
    """Create a new custom connector."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json() or {}
        connector_name = data.get("connector_name", "").strip()
        api_url = data.get("api_url", "").strip()
        auth_type = data.get("auth_type", "api_key").lower()
        if not connector_name:
            return jsonify({"success": False, "error": "connector_name is required"}), 400
        if not api_url:
            return jsonify({"success": False, "error": "api_url is required"}), 400
        connector_id = connector_name.lower().replace(" ", "_").replace("-", "_")
        connector_id = "".join(c for c in connector_id if c.isalnum() or c == "_")
        config = ConnectorConfig(
            connector_id=connector_id,
            connector_type=ConnectorType.CUSTOM_API,
            auth_config={"type": auth_type},
            custom_config={"base_url": api_url, "description": data.get("description", "")},
        )
        manager = get_connector_manager()
        manager.register_connector(CustomAPIConnector(config=config))
        return jsonify({
            "success": True,
            "connector_id": connector_id,
            "connector_name": connector_name,
            "message": f"Custom connector '{connector_name}' created successfully",
        }), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ===== Panel Orchestrator & Feature Access =====

_FEATURE_ACCESS = {
    "executive_brief": {"all", "oncall_lead", "incident_commander"},
    "progress_tracking": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "next_steps": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "timeline": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "data_filters": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "faqs": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "suggestions": {"all", "oncall_lead", "incident_commander"},
    "advanced_analytics": {"all", "incident_commander"},
    "risk_assessment": {"all", "oncall_lead", "incident_commander"},
    "compliance_reporting": {"all", "incident_commander"},
    "action_recommendations": {"all", "oncall_lead", "sre_engineer", "incident_commander"},
    "scenario_timeline": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "whatif_simulation": {"all", "oncall_lead", "sre_engineer", "incident_commander"},
    "premortem_generator": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
    "interactive_dashboard": {"all", "oncall_lead", "sre_engineer", "contractor", "incident_commander"},
}

_PERSONA_MAP = {
    "all": "all",
    "admin": "all",
    "oncall_lead": "oncall_lead",
    "sre_engineer": "sre_engineer",
    "contractor": "contractor",
    "incident_commander": "incident_commander",
    "Marco Reyes — On-Call Lead / SRE Lead": "oncall_lead",
    "Aisha Khan — SRE Engineer (on-call)": "sre_engineer",
    "Evan Cole — Contractor SRE (least privilege)": "contractor",
    "Helen Cho — Incident Commander / Director (escalation)": "incident_commander",
}


def _normalize_persona_id(persona_id: str | None) -> str:
    raw = (persona_id or "all").strip()
    mapped = _PERSONA_MAP.get(raw)
    if mapped:
        return mapped
    return raw.lower().replace(" ", "_").replace("-", "_")


def _can_access_feature(feature_name: str, persona_id: str | None) -> bool:
    key = (feature_name or "").lower().replace(" ", "_").replace("-", "_")
    allowed = _FEATURE_ACCESS.get(key, set())
    if not allowed:
        return False
    if "all" in allowed:
        return True
    return _normalize_persona_id(persona_id) in allowed


def _scenario_name() -> str:
    if sim_scenario is not None:
        root = getattr(sim_scenario, "root", None)
        if root is not None:
            name = getattr(root, "name", "")
            if name:
                return str(name)
    return "unknown"


def _generate_suggestions(sc_name: str) -> list[dict]:
    suggestions = {
        "c6-edkh": ["What are open action items?", "Show on-call escalations", "List pending owner reviews"],
        "c1-northbridge": ["What are the pending CAPA items?", "Show capacity planning status", "List open improvement actions"],
        "c2-contoso": ["What is blocking qualification?", "Who owns PPAP plan?", "Show OneNote recovery log summary"],
    }.get(sc_name, ["What is the current status?", "Show key action items", "List recent decisions"])
    return [{"label": s} for s in suggestions]


def _generate_timeline(conversation_history: list | None = None) -> list[dict]:
    timeline = [{"timestamp": datetime.now().isoformat(), "label": "Session started", "type": "session", "icon": "🚀"}]
    for item in (conversation_history or [])[:5]:
        if isinstance(item, dict):
            role = item.get("role", "user")
            content = str(item.get("content", "")).strip()
            if content:
                timeline.append({"timestamp": datetime.now().isoformat(), "label": f"{role.title()}: {content[:40]}...", "type": "message", "icon": "💬"})
    return timeline[:8]


def _generate_nextsteps(sc_name: str, last_response: str | None = None) -> list[dict]:
    base = [
        {"label": "Draft response", "icon": "✍️", "priority": "medium"},
        {"label": "Set reminder", "icon": "⏰", "priority": "low"},
        {"label": "Review sources", "icon": "📚", "priority": "medium"},
    ]
    if (last_response or "").lower().find("owner") >= 0:
        base.insert(0, {"label": "Verify ownership", "icon": "👤", "priority": "high"})
    return base[:5]


def _generate_progress(response_count: int = 0, citations: list | None = None) -> dict:
    kinds = {(c or {}).get("kind") for c in (citations or []) if isinstance(c, dict)}
    source_map = {"email": "Emails", "meeting": "Meetings", "teams_message": "Teams", "file": "Files", "onenote_page": "OneNote", "milestone": "Tables", "capa": "Tables"}
    source_categories = sorted({source_map[k] for k in kinds if k in source_map})
    coverage_percent = min(100, int((len(source_categories) / 6) * 100)) if source_categories else 0
    return {
        "response_count": response_count,
        "sources_used": source_categories,
        "coverage_percent": coverage_percent,
        "depth_score": min(10, (response_count * 2) + len(source_categories)),
        "citations_count": len(citations or []),
        "status": "active",
    }


@app.route("/api/agent/orchestrate", methods=["POST", "OPTIONS"])
def orchestrate_agents():
    """Orchestrate all panel agents — called on page load."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        sc_name = _scenario_name()
        return jsonify({
            "success": True,
            "suggestions": _generate_suggestions(sc_name),
            "timeline": _generate_timeline([]),
            "nextsteps": _generate_nextsteps(sc_name, None),
            "progress": _generate_progress(0, []),
        })
    except Exception as e:
        print(f"[ORCHESTRATOR] Error: {e}", file=sys.stderr)
        return jsonify({"success": False, "error": str(e), "suggestions": [], "timeline": [], "nextsteps": [], "progress": {}}), 500


@app.route("/api/agent/timeline", methods=["POST", "OPTIONS"])
def agent_timeline():
    """Generate timeline after messages are processed."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json(silent=True) or {}
        timeline = _generate_timeline(data.get("conversation_history", []))
        return jsonify({"success": True, "timeline": timeline})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "timeline": []}), 500


@app.route("/api/agent/nextsteps", methods=["POST", "OPTIONS"])
def agent_nextsteps():
    """Generate next steps after a response."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json(silent=True) or {}
        nextsteps = _generate_nextsteps(_scenario_name(), data.get("last_response"))
        return jsonify({"success": True, "nextsteps": nextsteps})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "nextsteps": []}), 500


def _generate_exec_brief(sc_name: str) -> dict:
    summary = {
        "c2-contoso": "Contoso milestone qualification on track. Key stakeholder alignment achieved.",
        "c6-edkh": "EDKH platform stabilizing. On-call operations nominal and action tracking improving.",
    }.get(sc_name, f"Status update for {sc_name}. Monitoring key metrics and progress.")
    return {
        "summary": summary,
        "risks": [{"level": "medium", "description": "General project risks under review"}],
        "blockers": [{"description": "Stakeholder approvals pending", "owner": "TBD", "due": "2026-07-15"}],
        "next_actions": [{"action": "Review project status", "owner": "Project Manager", "due": "2026-07-10", "priority": "medium"}],
        "overall_health": "Healthy",
        "timestamp": datetime.now().isoformat(),
    }


def _generate_action_recommendations(sc_name: str) -> dict:
    today = datetime.now()
    actions = [
        {
            "action": "Review pending items",
            "description": "Assess all pending work items and prioritize next steps",
            "owner": "Team Lead",
            "owner_role": "Manager",
            "due_date": (today + timedelta(days=7)).isoformat(),
            "priority": "medium",
            "category": "General",
            "status": "pending",
        },
        {
            "action": "Schedule stakeholder sync",
            "description": "Align on priorities and resource needs with stakeholders",
            "owner": "Project Manager",
            "owner_role": "Coordinator",
            "due_date": (today + timedelta(days=3)).isoformat(),
            "priority": "high",
            "category": "Communication",
            "status": "pending",
        },
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "context": "Scenario-aligned recommended actions",
        "actions": actions,
        "total_actions": len(actions),
        "critical_count": 0,
        "high_count": 1,
        "timestamp": datetime.now().isoformat(),
    }


def _generate_scenario_timeline(sc_name: str) -> dict:
    events = [
        {"timestamp": "2026-07-06T14:30:00Z", "category": "Alert", "actor": "Monitoring System", "title": "Issue Detection", "description": "Alert fired for high resource usage", "severity": "high"},
        {"timestamp": "2026-07-06T14:45:00Z", "category": "Response", "actor": "On-call Engineer", "title": "Investigation Started", "description": "Root cause analysis initiated", "severity": "medium"},
        {"timestamp": "2026-07-06T15:00:00Z", "category": "Resolution", "actor": "Operations", "title": "Service Stabilized", "description": "Mitigation applied and service health restored", "severity": "low"},
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "scenario_display": f"{sc_name} Timeline",
        "context": "Chronological reconstruction of key events",
        "events": events,
        "total_events": len(events),
        "critical_count": 0,
        "high_count": 1,
        "duration": "~30 minutes",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _generate_whatif_simulation(sc_name: str) -> dict:
    scenarios = [
        {"name": "Optimistic Path", "description": "Best case with no new blockers", "probability": 0.4, "impact": "No delay", "adjusted_timeline": "On Schedule", "risk_level": "low", "affected_milestones": 0},
        {"name": "Expected Path", "description": "Minor dependency delays", "probability": 0.45, "impact": "1-week delay", "adjusted_timeline": "+7 days", "risk_level": "medium", "affected_milestones": 1},
        {"name": "Pessimistic Path", "description": "Major issue in critical path", "probability": 0.15, "impact": "3-week delay", "adjusted_timeline": "+21 days", "risk_level": "high", "affected_milestones": 2},
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "scenario_display": f"{sc_name} What-If",
        "baseline_timeline": "Current baseline",
        "baseline_milestones": [{"name": "Milestone 1", "date": "2026-07-15", "status": "Planned"}],
        "scenarios": scenarios,
        "total_scenarios": len(scenarios),
        "weighted_risk_delay_days": 6,
        "recommendation": "Expected delay: ~6 days. Monitor critical path milestones.",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _generate_premortem(sc_name: str, persona_id: str) -> dict:
    return {
        "scenario_display": f"{sc_name} Reliability Program",
        "active_milestone": "Upcoming Milestone",
        "target_date": "2026-07-31",
        "risk_window_days": 14,
        "risk_score": 1.4,
        "highest_risk_mode": "Dependency delay",
        "failure_modes": [
            {"name": "Dependency delay", "probability": 0.3, "impact": "medium", "early_signal": "Critical dependencies remain unconfirmed", "blast_radius": "Milestone date likely to slip"},
        ],
        "preventive_actions": [
            {"action": "Set contingency owner and fallback plan", "owner": "Program Manager", "due": "2026-07-10", "priority": "high"},
        ],
        "recommendation": "Execute high-priority preventive actions within 48 hours and verify early signals daily.",
        "generated_for_persona": persona_id or "all",
        "timestamp": datetime.now().isoformat(),
    }


def _generate_progress_tracking(sc_name: str) -> dict:
    points = [
        {"day": "Day 1", "value": 50, "status": "flat", "incidents": 2},
        {"day": "Day 2", "value": 55, "status": "improving", "incidents": 1},
        {"day": "Day 3", "value": 60, "status": "improving", "incidents": 1},
        {"day": "Day 4", "value": 65, "status": "improving", "incidents": 1},
        {"day": "Day 5", "value": 70, "status": "improving", "incidents": 0},
        {"day": "Day 6", "value": 75, "status": "improving", "incidents": 0},
        {"day": "Day 7", "value": 80, "status": "improving", "incidents": 0},
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "scenario_display": f"{sc_name} Progress",
        "trend_label": "Activity Trend",
        "data_points": points,
        "summary": "Activity trending upward with improving engagement metrics.",
        "activities": ["Initial analysis", "Planning phase", "Execution started", "Progress monitoring"],
        "trend_direction": "upward",
        "trend_percentage": 60,
        "total_incidents": 5,
        "avg_daily_incidents": 1,
        "current_value": 80,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _generate_interactive_dashboard(sc_name: str) -> dict:
    kpis = [
        {"label": "Overall Progress", "value": "72%", "target": "80%", "status": "warning"},
        {"label": "Critical Issues", "value": "0", "target": "0", "status": "success"},
        {"label": "Team Alignment", "value": "85%", "target": ">80%", "status": "success"},
    ]
    return {
        "success": True,
        "scenario": sc_name,
        "scenario_display": f"{sc_name} Dashboard",
        "health_status": "On Track",
        "health_color": "green",
        "kpis": kpis,
        "kpi_summary": {"total": len(kpis), "critical": 0, "warning": 1, "success": 2},
        "top_blockers": [{"title": "Generic blocker", "severity": "medium", "owner": "Team Lead", "age_days": 1}],
        "blocker_count": 1,
        "top_actions": [{"action": "Review metrics", "owner": "Manager", "due": "2026-07-10", "priority": "medium"}],
        "action_count": 1,
        "critical_action_count": 0,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.route("/api/feature-acl", methods=["GET", "OPTIONS"])
def feature_acl():
    """Return feature access control list for current persona."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        active_persona = session.get("persona_id", "all")
        normalized = _normalize_persona_id(active_persona)
        allowed_features = [feature for feature in _FEATURE_ACCESS if _can_access_feature(feature, active_persona)]
        acl_dict = {feature: _can_access_feature(feature, active_persona) for feature in _FEATURE_ACCESS}
        return jsonify({
            "success": True,
            "persona_id": normalized,
            "allowed_features": allowed_features,
            "acl": acl_dict,
        })
    except Exception as e:
        print(f"[FEATURE_ACL] Error: {e}", file=sys.stderr)
        return jsonify({"success": False, "error": str(e), "acl": {}}), 500


@app.route("/api/agent/progress-trend", methods=["POST", "OPTIONS"])
def agent_progress_trend():
    """Generate 7-day trend data for progress visualization."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        trend_values = [50, 55, 60, 65, 70, 75, 80]
        today = datetime.now()
        trend_data = [(today - timedelta(days=6 - i)).strftime('%Y-%m-%d') for i in range(7)]
        return jsonify({
            "success": True,
            "trend": trend_values,
            "trendDirection": "improving",
            "trendDescription": "↑ Trending up - Improved activity",
            "dates": trend_data,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "trend": []}), 500


@app.route("/api/agent/executive-brief", methods=["POST", "OPTIONS"])
def agent_executive_brief():
    """Generate executive brief."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        persona_id = session.get("persona_id", "all")
        if not _can_access_feature("executive_brief", persona_id):
            return jsonify({"success": False, "error": "Access denied for this persona"}), 403
        return jsonify({"success": True, **_generate_exec_brief(_scenario_name())})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/action-recommendations", methods=["POST", "OPTIONS"])
def agent_action_recommendations():
    """Generate action recommendations."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        persona_id = session.get("persona_id", "all")
        if not _can_access_feature("action_recommendations", persona_id):
            return jsonify({"success": False, "error": "Access denied for this persona"}), 403
        return jsonify(_generate_action_recommendations(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/scenario-timeline", methods=["POST", "OPTIONS"])
def agent_scenario_timeline():
    """Generate scenario timeline."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify(_generate_scenario_timeline(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/whatif-simulation", methods=["POST", "OPTIONS"])
def agent_whatif_simulation():
    """Generate what-if simulation."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        persona_id = session.get("persona_id", "all")
        if not _can_access_feature("whatif_simulation", persona_id):
            return jsonify({"success": False, "error": "Access denied for this persona"}), 403
        return jsonify(_generate_whatif_simulation(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/pre-mortem-generator", methods=["POST", "OPTIONS"])
def agent_premortem():
    """Generate pre-mortem analysis."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        persona_id = session.get("persona_id", "all")
        if not _can_access_feature("premortem_generator", persona_id):
            return jsonify({"success": False, "error": "Access denied for this persona"}), 403
        return jsonify({"success": True, **_generate_premortem(_scenario_name(), persona_id)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/progress-tracking", methods=["POST", "OPTIONS"])
def agent_progress_tracking():
    """Generate progress tracking data."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify(_generate_progress_tracking(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agent/interactive-dashboard", methods=["POST", "OPTIONS"])
def agent_interactive_dashboard():
    """Generate interactive dashboard data."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify(_generate_interactive_dashboard(_scenario_name()))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/connectors/<connector_id>/resources", methods=["GET", "OPTIONS"])
def get_connector_resources(connector_id):
    """Get supported resources for a connector."""
    try:
        if request.method == "OPTIONS":
            return ("", 204)
        manager = get_connector_manager()
        connector = manager.get_connector(connector_id)
        if not connector:
            return jsonify({"success": False, "error": f"Connector not found: {connector_id}"}), 404
        return jsonify({
            "success": True,
            "connector_id": connector_id,
            "connector_name": connector.connector_name,
            "resources": connector.supported_resources,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    """Handle 500 errors."""
    return jsonify({"error": "Internal server error"}), 500


def main():
    """Main entry point."""
    print("⏳ Initializing Work IQ Agent Web UI...")

    port = int(os.getenv("WORKIQ_PORT", "5000"))

    if not init_app():
        print("\n Failed to initialize app. Please check your configuration.", file=sys.stderr)
        print("\nRequired environment variables:")
        print("  - WORKIQ_AZURE_ENDPOINT")
        print("\nFor MCP transport (initialized on first request):")
        print("  - WORKIQ_MCP_COMMAND")
        print("  - WORKIQ_MCP_ARGS")
        print("\nFor A2A transport (initialized on first request):")
        print("  - WORKIQ_A2A_URL (default: http://127.0.0.1:8920)")
        sys.exit(1)

    print("App initialized! Agents will be created on first request per transport.")
    print("\n Starting Web Server...")
    print(f"   Open your browser and go to: http://localhost:{port}")
    print("   Press CTRL+C to stop the server\n")

    # Run the Flask app
    app.run(
        host="127.0.0.1",
        port=port,
        debug=False,
        use_reloader=False
    )


if __name__ == "__main__":
    main()
