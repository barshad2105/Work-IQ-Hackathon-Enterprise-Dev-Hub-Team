"""
Web UI for the Work IQ Agent using Flask.
Provides a browser-based chat interface.
"""

import os
import asyncio
import sys
import shlex
from datetime import datetime
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


def _get_required_env(name: str) -> str:
    """Return a required env var value or raise a helpful error."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def init_agent():
    """Initialize the agent on app startup."""
    global agent, mcp_tool
    try:
        # Setup Azure OpenAI client
        endpoint = _get_required_env("WORKIQ_AZURE_ENDPOINT")
        model = os.getenv("WORKIQ_MODEL", "gpt-5-mini")
        api_version = os.getenv("WORKIQ_AZURE_API_VERSION", "2024-08-01-preview")

        client = OpenAIChatCompletionClient(
            model=model,
            credential=DefaultAzureCredential(),
            azure_endpoint=endpoint,
            api_version=api_version,
        )

        # Setup MCP stdio tool for Work IQ
        mcp_command = _get_required_env("WORKIQ_MCP_COMMAND")
        mcp_args = shlex.split(os.getenv("WORKIQ_MCP_ARGS", ""), posix=False)
        persona = os.getenv("WORKIQ_SIM_PERSONA", "quality_engineer")
        scenario = os.getenv("WORKIQ_SIM_SCENARIO", r"scenarios\c2-contoso")

        mcp_tool = MCPStdioTool(
            name="workiq-mcp",
            command=mcp_command,
            args=mcp_args,
            env={
                **os.environ,
                "WORKIQ_SIM_PERSONA": persona,
                "WORKIQ_SIM_SCENARIO": scenario,
            },
        )

        # Create agent
        agent = Agent(
            client=client,
            name="WorkIQAgent",
            instructions="""You are a helpful Work IQ assistant. 
You have access to Work IQ tools through the connected MCP server:
- ask_work_iq: Query Work IQ for information about people, meetings, emails, files
- fetch: Read rows from Work IQ tables
- create_entity: Create new rows in Work IQ tables
- update_entity: Update existing rows in Work IQ tables

Use these tools to help answer user questions about their work context.""",
            tools=[mcp_tool],
        )
        
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


@app.route("/")
def index():
    """Serve the main chat interface."""
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    """Handle chat messages via API."""
    try:
        data = request.json
        user_message = data.get("message", "").strip()

        if not user_message:
            return jsonify({"error": "Empty message"}), 400

        if not agent or not mcp_tool:
            return jsonify({"error": "Agent not initialized"}), 500

        # Run the async agent call from the sync Flask handler
        async def run_agent():
            async with mcp_tool:
                response = await agent.run(user_message)
                return response

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        response = loop.run_until_complete(run_agent())

        # Extract the actual response text from AgentResponse object
        response_text = str(response) if response else ""

        return jsonify({
            "success": True,
            "response": response_text,
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


@app.route("/api/clear", methods=["POST"])
def clear_history():
    """Clear the conversation history."""
    try:
        # The agent maintains its own conversation history
        return jsonify({"success": True, "message": "Ready for new conversation"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def status():
    """Get agent status."""
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
        print("  - WORKIQ_AZURE_ENDPOINT")
        print("  - WORKIQ_MCP_COMMAND")
        print("  - WORKIQ_MCP_ARGS")
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
