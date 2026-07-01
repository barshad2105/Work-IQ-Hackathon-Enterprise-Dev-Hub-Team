"""
Web UI for the Work IQ Agent using Flask.
Provides a browser-based chat interface.
"""

import os
import asyncio
import sys
import shlex
import json
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, session
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient
from agent_framework import MCPStdioTool

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your-secret-key-change-in-production")

# Global agent instance
agent = None
mcp_tool = None
sim_engine = None
sim_scenario = None
sim_persona = None
simulator_only = False
model_client = None
mcp_command_cfg = None
mcp_args_cfg = []
available_personas = []

AGENT_INSTRUCTIONS = """You are a helpful Work IQ assistant.
You have access to Work IQ tools through the connected MCP server:
- ask_work_iq: Query Work IQ for information about people, meetings, emails, Teams chats, files, and OneNote pages
- fetch: Read rows from Work IQ tables
- create_entity: Create new rows in Work IQ tables
- update_entity: Update existing rows in Work IQ tables

Use these tools to help answer user questions about their work context."""


def _extract_citations(response_obj) -> list:
    """Best-effort citation extraction across possible agent response shapes."""
    # Direct list on known dict/object shapes.
    try:
        if isinstance(response_obj, dict):
            cits = response_obj.get("citations")
            if isinstance(cits, list):
                return cits
        cits = getattr(response_obj, "citations", None)
        if isinstance(cits, list):
            return cits
    except Exception:
        pass

    # Some SDK responses expose nested payloads.
    for attr in ("output", "result", "data", "message"):
        try:
            nested = getattr(response_obj, attr, None)
            if isinstance(nested, dict):
                cits = nested.get("citations")
                if isinstance(cits, list):
                    return cits
            elif nested is not None:
                cits = getattr(nested, "citations", None)
                if isinstance(cits, list):
                    return cits
        except Exception:
            continue

    return []


def _maybe_enforce_source_intent(sc, engine_module, question: str, persona_id: str | None, result: dict) -> dict:
    """If a source-specific question (e.g., OneNote) returns mismatched golden sources,
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


def _build_demo_trace(
    question: str,
    active_persona: str,
    mode: str,
    citations: list,
    source: str | None,
    matched: str | None,
    transport: str,
) -> dict:
    """Build a demo-friendly trace payload for UI flyout."""
    files_used = []
    seen = set()
    for c in citations:
        kind = (c or {}).get("kind", "")
        f = _fixture_for_kind(kind)
        if f not in seen:
            seen.add(f)
            files_used.append(f)

    steps = [
        f"Received question over REST: {question[:120]}",
        f"Applied active persona: {active_persona}",
        f"Selected transport mode: {transport}",
        f"Execution path: {mode}",
    ]

    if matched:
        steps.append(f"Golden answer matched: {matched}")
    elif source:
        steps.append(f"Answer source mode: {source}")

    if citations:
        steps.append(f"Resolved citations: {len(citations)}")
    else:
        steps.append("No citations resolved for this response")

    return {
        "transport": transport,
        "mode": mode,
        "active_persona": active_persona,
        "source": source,
        "matched": matched,
        "files_used": files_used,
        "steps": steps,
    }

def _is_allowed_origin(origin: str | None) -> bool:
    """Allow local-dev browser origins (Live Server / Flask) on any localhost port."""
    if not origin:
        return False

    try:
        parsed = urlparse(origin)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    return parsed.hostname in {"127.0.0.1", "localhost"}


def _get_required_env(name: str) -> str:
    """Return a required env var value or raise a helpful error."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


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


def _load_personas_for_scenario(scenario_path: Path) -> list[dict]:
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


def init_agent():
    """Initialize the agent on app startup."""
    global agent, mcp_tool, sim_engine, sim_scenario, sim_persona, simulator_only
    global model_client, mcp_command_cfg, mcp_args_cfg, available_personas
    try:
        endpoint = os.getenv("WORKIQ_AZURE_ENDPOINT", "").strip()
        raw_scenario = os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c2-contoso")
        scenario_path = _resolve_scenario_path(raw_scenario)
        available_personas = _load_personas_for_scenario(scenario_path)
        sim_persona = os.getenv("WORKIQ_SIM_PERSONA", "quality_engineer").strip() or "all"

        # Simulator-only mode: if no Azure endpoint is configured, answer directly from
        # simulator engine (same behavior family as simulator/demo.py).
        if not endpoint:
            simulator_dir = Path(__file__).resolve().parent / "simulator"
            if str(simulator_dir) not in sys.path:
                sys.path.insert(0, str(simulator_dir))

            import engine as sim_engine_module  # type: ignore

            sim_scenario = sim_engine_module.load_scenario(str(scenario_path))
            sim_engine = sim_engine_module
            simulator_only = True

            # Keep non-None sentinel for status checks.
            agent = object()
            mcp_tool = None
            model_client = None
            return True

        # Setup Azure OpenAI client
        model = os.getenv("WORKIQ_MODEL", "gpt-5-mini")
        api_version = os.getenv("WORKIQ_AZURE_API_VERSION", "2024-08-01-preview")

        model_client = OpenAIChatCompletionClient(
            model=model,
            credential=DefaultAzureCredential(),
            azure_endpoint=endpoint,
            api_version=api_version,
        )

        # Setup MCP stdio tool for Work IQ
        mcp_command_cfg = _get_required_env("WORKIQ_MCP_COMMAND")
        mcp_args_cfg = shlex.split(os.getenv("WORKIQ_MCP_ARGS", ""), posix=False)
        mcp_tool = object()

        # Create agent
        agent = object()
        simulator_only = False
        
        return True
    except Exception as e:
        print(f"Failed to initialize agent: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


@app.before_request
def before_request():
    """Initialize session if needed."""
    if "conversation_id" not in session:
        session["conversation_id"] = str(datetime.now().timestamp())

    if "persona_id" not in session:
        session["persona_id"] = sim_persona or "all"


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
    """Serve the main chat interface."""
    return render_template("index.html")


@app.route("/api/personas", methods=["GET", "OPTIONS"])
def get_personas():
    """Return available simulator personas and the active selection."""
    if request.method == "OPTIONS":
        return ("", 204)

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
        "active_persona": session.get("persona_id", sim_persona or "all")
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
            "valid": sorted(valid_personas)
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
        transport_mode = str(data.get("transport", "MCP")).strip().upper() or "MCP"

        if not user_message:
            return jsonify({"error": "Empty message"}), 400

        if not agent:
            return jsonify({"error": "Agent not initialized"}), 500

        if simulator_only:
            active_persona = session.get("persona_id", sim_persona or "all")
            persona_id = None if (active_persona or "").lower() == "all" else active_persona
            result = sim_engine.ask(sim_scenario, user_message, persona_id=persona_id)
            result = _maybe_enforce_source_intent(sim_scenario, sim_engine, user_message, persona_id, result)
            citations = result.get("citations", [])
            trace = _build_demo_trace(
                question=user_message,
                active_persona=active_persona,
                mode="simulator-only",
                citations=citations,
                source=result.get("source"),
                matched=result.get("matched"),
                transport=transport_mode,
            )
            return jsonify({
                "success": True,
                "response": result.get("response", ""),
                "citations": citations,
                "source": result.get("source"),
                "matched": result.get("matched"),
                "trace": trace,
                "active_persona": active_persona,
                "timestamp": datetime.now().isoformat()
            })

        if not model_client or not mcp_command_cfg:
            return jsonify({"error": "MCP tool not initialized"}), 500

        active_persona = session.get("persona_id", sim_persona or "all")
        scenario = os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c2-contoso")

        request_tool = MCPStdioTool(
            name="workiq-mcp",
            command=mcp_command_cfg,
            args=mcp_args_cfg,
            env={
                **os.environ,
                "WORKIQ_SIM_PERSONA": active_persona,
                "WORKIQ_SIM_SCENARIO": scenario,
            },
        )

        request_agent = Agent(
            client=model_client,
            name="WorkIQAgent",
            instructions=AGENT_INSTRUCTIONS,
            tools=[request_tool],
        )

        # Run the async agent call from the sync Flask handler
        async def run_agent():
            async with request_tool:
                response = await request_agent.run(user_message)
                return response

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        response = loop.run_until_complete(run_agent())

        # Extract the actual response text from AgentResponse object
        response_text = str(response) if response else ""
        citations = _extract_citations(response)
        trace = _build_demo_trace(
            question=user_message,
            active_persona=active_persona,
            mode="agent+mcp",
            citations=citations,
            source=None,
            matched=None,
            transport=transport_mode,
        )

        return jsonify({
            "success": True,
            "response": response_text,
            "citations": citations,
            "trace": trace,
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

        # The agent maintains its own conversation history
        return jsonify({"success": True, "message": "Ready for new conversation"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def status():
    """Get agent status."""
    if agent and simulator_only:
        configured_persona = os.getenv("WORKIQ_SIM_PERSONA", "quality_engineer")
        configured_scenario = os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c2-contoso")
        active_persona = session.get("persona_id", sim_persona or configured_persona)
        return jsonify({
            "status": "ready",
            "mode": "simulator-only",
            "model": "none",
            "endpoint": "none",
            "mcp_server": "not-used",
            "persona": configured_persona,
            "active_persona": active_persona,
            "scenario": configured_scenario
        })

    if agent and mcp_tool:
        configured_endpoint = os.getenv("WORKIQ_AZURE_ENDPOINT", "")
        configured_model = os.getenv("WORKIQ_MODEL", "gpt-5-mini")
        configured_persona = os.getenv("WORKIQ_SIM_PERSONA", "quality_engineer")
        configured_scenario = os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c2-contoso")

        return jsonify({
            "status": "ready",
            "model": configured_model,
            "endpoint": configured_endpoint,
            "mcp_server": "Work IQ Simulator",
            "persona": configured_persona,
            "scenario": configured_scenario
        })
    else:
        return jsonify({
            "status": "not_initialized",
            "error": "Agent not initialized"
        }), 500


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

    if not init_agent():
        print("\n❌ Failed to initialize agent. Please check your configuration.", file=sys.stderr)
        print("\nRequired environment variables:")
        print("  - For full agent+MCP mode: WORKIQ_AZURE_ENDPOINT, WORKIQ_MCP_COMMAND, WORKIQ_MCP_ARGS")
        print("  - For simulator-only mode: WORKIQ_SIM_SCENARIO (optional), WORKIQ_SIM_PERSONA (optional)")
        sys.exit(1)

    print("✅ Agent initialized!")
    print("\n🌐 Starting Web Server...")
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
