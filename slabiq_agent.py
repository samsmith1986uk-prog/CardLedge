#!/usr/bin/env python3
"""
SlabIQ Agent — Terminal AI assistant for the SlabIQ project.
Tell it what you want in plain English. It plans, executes, tests, and fixes.

Usage: python3 slabiq_agent.py
"""

import subprocess
import sys
import os
import json
import urllib.request
import urllib.error

ANTHROPIC_API_KEY = ""
MODEL = "claude-sonnet-4-20250514"
PROJECT_DIR = os.path.expanduser("~/Downloads/cardledge-backend")

SYSTEM_PROMPT = """You are SlabIQ Agent — an expert backend engineer working on the SlabIQ sports card intelligence platform.

You have FULL ACCESS to run terminal commands on the user's Mac. When given a task:
1. Break it into steps
2. Run each step using run_command
3. Check output and fix errors automatically
4. Keep going until the task is DONE — don't ask the user to run things
5. Report what you did and the final result

The project is at ~/Downloads/cardledge-backend
- FastAPI backend, Python 3.14, venv at ~/Downloads/cardledge-backend/venv
- Always activate venv: source ~/Downloads/cardledge-backend/venv/bin/activate
- Server runs on port 8000 with uvicorn
- Key files: main.py, scrapers/card_resolver.py, scrapers/psa.py, static/index.html
- .env has PSA_API_TOKEN and ANTHROPIC_API_KEY

When writing files, write complete files — never partial patches.
When something fails, read the error, fix it, and retry automatically.
Don't ask the user to do anything — DO IT YOURSELF.

Available tools: run_command, write_file, read_file"""

TOOLS = [
    {
        "name": "run_command",
        "description": "Run a shell command on the Mac terminal. Returns stdout + stderr. Always activate venv first when running Python.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, use 120 for installs/scraping tests)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "write_file",
        "description": "Write complete content to a file on disk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full path to file"},
                "content": {"type": "string", "description": "Complete file content"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "read_file",
        "description": "Read a file from disk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full path to file"}
            },
            "required": ["path"]
        }
    }
]

def run_command(command: str, timeout: int = 30) -> str:
    """Execute a shell command and return output."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            executable="/bin/zsh"
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += "\nSTDERR: " + result.stderr
        if result.returncode != 0:
            output += f"\nEXIT CODE: {result.returncode}"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"

def write_file(path: str, content: str) -> str:
    """Write content to file."""
    try:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR writing file: {e}"

def read_file(path: str) -> str:
    """Read file content."""
    try:
        path = os.path.expanduser(path)
        with open(path, 'r') as f:
            content = f.read()
        return content[:8000]  # Cap at 8k chars
    except Exception as e:
        return f"ERROR reading file: {e}"

def call_tool(name: str, inputs: dict) -> str:
    """Dispatch tool call."""
    if name == "run_command":
        return run_command(inputs["command"], inputs.get("timeout", 30))
    elif name == "write_file":
        return write_file(inputs["path"], inputs["content"])
    elif name == "read_file":
        return read_file(inputs["path"])
    return f"Unknown tool: {name}"

def call_claude(messages: list, max_tokens: int = 4096) -> dict:
    """Call Anthropic API directly."""
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "tools": TOOLS,
        "messages": messages
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01"
        }
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())

def load_api_key():
    """Load API key from .env file."""
    global ANTHROPIC_API_KEY
    env_path = os.path.join(PROJECT_DIR, ".env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    ANTHROPIC_API_KEY = line.strip().split("=", 1)[1]
                    return True
    except:
        pass
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if key:
        ANTHROPIC_API_KEY = key
        return True
    return False

def run_agent(user_message: str, history: list) -> tuple[str, list]:
    """Run the agent loop for a single user message."""
    history.append({"role": "user", "content": user_message})
    messages = history.copy()

    print("\n🤖 Agent thinking...\n")

    while True:
        response = call_claude(messages)
        stop_reason = response.get("stop_reason")
        content = response.get("content", [])

        # Print any text blocks
        for block in content:
            if block.get("type") == "text":
                print(block["text"])

        # Add assistant response to messages
        messages.append({"role": "assistant", "content": content})

        # If done, extract final text and return
        if stop_reason == "end_turn":
            final_text = " ".join(b.get("text","") for b in content if b.get("type") == "text")
            history.append({"role": "assistant", "content": content})
            return final_text, history

        # Handle tool calls
        if stop_reason == "tool_use":
            tool_results = []
            for block in content:
                if block.get("type") == "tool_use":
                    tool_name = block["name"]
                    tool_input = block["input"]
                    tool_id = block["id"]

                    print(f"\n⚙️  [{tool_name}] {str(tool_input)[:120]}...")
                    result = call_tool(tool_name, tool_input)
                    
                    # Show truncated output
                    display = result[:500] + "..." if len(result) > 500 else result
                    print(f"   → {display}\n")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result[:4000]  # Cap tool results
                    })

            messages.append({"role": "user", "content": tool_results})

        else:
            # Unexpected stop
            break

    history.append({"role": "assistant", "content": content})
    return "", history

def main():
    print("=" * 60)
    print("  SlabIQ Agent 🤖")
    print("  Tell me what you want. I'll handle everything.")
    print("  Type 'exit' to quit, 'clear' to reset context")
    print("=" * 60)

    if not load_api_key():
        print("❌ Could not find ANTHROPIC_API_KEY in .env or environment")
        sys.exit(1)

    print(f"✅ API key loaded | Project: {PROJECT_DIR}\n")

    history = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() == "exit":
            break
        if user_input.lower() == "clear":
            history = []
            print("🔄 Context cleared\n")
            continue

        try:
            _, history = run_agent(user_input, history)
        except urllib.error.HTTPError as e:
            print(f"❌ API error: {e.code} {e.read().decode()}")
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
