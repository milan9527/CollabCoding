"""Minimal coding agent for AgentCore Runtime.

All heavy imports are deferred to first invocation to stay within
the 30-second initialization timeout.
"""
import os
os.environ["BYPASS_TOOL_CONSENT"] = "true"

from bedrock_agentcore import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

WORKSPACE = "/mnt/workspace"

SYSTEM_PROMPT = (
    "You are CodeSpace AI, a collaborative coding assistant. "
    "You help developers, designers, and product managers build websites. "
    "When generating code, write files to the workspace path provided. "
    "Create clean, well-structured HTML/CSS/JS. "
    "IMPORTANT RULES FOR WRITING FILES: "
    "1. Write only ONE file at a time using the file_write tool. "
    "2. After each file_write, run: shell command 'sync' to flush to disk. "
    "3. Keep each file under 200 lines to avoid write buffer issues. "
    "4. If you need CSS, put it inline in a <style> tag inside the HTML file instead of a separate .css file. "
    "5. If you need JS, put it inline in a <script> tag inside the HTML file instead of a separate .js file. "
    "6. Prefer creating a SINGLE self-contained HTML file when possible. "
    "After writing files, respond with ONLY this JSON (no markdown, no code blocks): "
    '{"response": "short description", "files_changed": ["file1.html"]}. '
    "Use short filenames only (not full paths). Keep your response text brief."
)

_agent = None


@app.entrypoint
def handle_request(payload):
    global _agent

    space_id = payload.get("space_id", "default")
    workspace_path = payload.get("workspace_path", f"{WORKSPACE}/{space_id}")
    action = payload.get("action", "generate")

    os.makedirs(workspace_path, exist_ok=True)

    # ---- Direct file I/O (no LLM, instant) --------------------------------
    if action == "direct_write":
        fp = payload.get("file_path", "")
        content = payload.get("content", "")
        full_path = os.path.join(workspace_path, fp) if not fp.startswith("/") else fp
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        os.sync()
        return {"response": "ok", "files_changed": [fp]}

    if action == "direct_read":
        fp = payload.get("file_path", "")
        full_path = os.path.join(workspace_path, fp) if not fp.startswith("/") else fp
        try:
            with open(full_path, "r") as f:
                content = f.read()
            return {"response": "ok", "content": content}
        except FileNotFoundError:
            return {"response": "not found", "content": ""}

    if action == "direct_read_batch":
        file_paths = payload.get("file_paths", [])
        result = {}
        for fp in file_paths:
            full_path = os.path.join(workspace_path, fp) if not fp.startswith("/") else fp
            try:
                with open(full_path, "r") as f:
                    result[fp] = f.read()
            except FileNotFoundError:
                result[fp] = ""
        return {"response": "ok", "file_contents": result}

    if action == "direct_list":
        files = []
        for name in os.listdir(workspace_path):
            full = os.path.join(workspace_path, name)
            files.append({"path": name, "name": name, "is_directory": os.path.isdir(full)})
        return {"response": "ok", "files": files}

    # ---- LLM-powered actions (code generation) ----------------------------
    if _agent is None:
        from strands import Agent
        from strands.models import BedrockModel
        from strands_tools import file_read, file_write, shell
        model = BedrockModel(model_id="us.anthropic.claude-sonnet-4-20250514-v1:0")
        _agent = Agent(
            model=model,
            tools=[file_read, file_write, shell],
            system_prompt=SYSTEM_PROMPT,
        )

    prompt = payload.get("prompt", "")

    if action == "read_file":
        fp = payload.get("file_path", "")
        full_prompt = f"Read the file at {fp} and return its contents in JSON 'content' field."
    elif action == "write_file":
        fp = payload.get("file_path", "")
        content = payload.get("content", "")
        full_prompt = f"Write this content to {fp}:\n\n{content}"
    elif action == "list_files":
        full_prompt = f"List all files in {workspace_path} recursively."
    else:
        full_prompt = f"Workspace: {workspace_path}\n\n{prompt}"

    response = _agent(full_prompt)
    text = response.message["content"][0]["text"]

    return {
        "response": text,
        "session_id": payload.get("session_id", "default"),
        "space_id": space_id,
    }


if __name__ == "__main__":
    app.run()
