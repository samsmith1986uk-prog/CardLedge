#!/usr/bin/env python3
import subprocess, json, os, time, sys, urllib.request, traceback

MODEL = "claude-sonnet-4-20250514"
PROJECT_DIR = os.path.expanduser("~/Downloads/cardledge-backend")
QUEUE_FILE = "/tmp/slabiq_tasks.json"

SYSTEM = """You are the SlabIQ Mac Agent. You have full control of the user's Mac terminal.
Your job: execute tasks autonomously. When given a task:
1. Plan the steps
2. Use run_command to execute each step  
3. Read output, fix errors, retry automatically
4. Keep going until DONE - never stop halfway
5. Report back with what you did

Project: ~/Downloads/cardledge-backend (FastAPI, Python 3.14)
Venv activate command: source ~/Downloads/cardledge-backend/venv/bin/activate
All python/pip commands must be prefixed with the venv activate.
Server runs on port 8000 with uvicorn.

RULES:
- Never ask the user to do anything
- Always fix errors yourself and retry
- Write complete files, never partial patches
- Test your work before calling task_complete"""

TOOLS = [
    {
        "name": "run_command",
        "description": "Run any shell command on the Mac. Always use full paths. Returns stdout+stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "seconds, default 30, use 120 for installs"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "write_file",
        "description": "Write complete content to a file on the Mac filesystem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full path e.g. /Users/samsmith/Downloads/cardledge-backend/scrapers/card_resolver.py"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "read_file",
        "description": "Read a file from the Mac filesystem.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "name": "task_complete",
        "description": "Call this when the task is fully done.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"]
        }
    }
]

def run_command(command, timeout=30):
    try:
        full = f"source {PROJECT_DIR}/venv/bin/activate 2>/dev/null; {command}"
        result = subprocess.run(full, shell=True, capture_output=True, text=True,
                                timeout=timeout, executable="/bin/zsh", cwd=PROJECT_DIR)
        out = result.stdout
        if result.stderr: out += "\nSTDERR: " + result.stderr
        if result.returncode != 0: out += f"\nEXIT: {result.returncode}"
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"

def write_file(path, content):
    try:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'w') as f: f.write(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR: {e}"

def read_file(path):
    try:
        with open(os.path.expanduser(path)) as f: return f.read()[:6000]
    except Exception as e:
        return f"ERROR: {e}"

def call_tool(name, inputs):
    if name == "run_command": return run_command(inputs["command"], inputs.get("timeout", 30))
    if name == "write_file": return write_file(inputs["path"], inputs["content"])
    if name == "read_file": return read_file(inputs["path"])
    if name == "task_complete": return f"DONE: {inputs['summary']}"
    return f"Unknown tool: {name}"

def load_key():
    try:
        with open(f"{PROJECT_DIR}/.env") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.strip().split("=",1)[1]
    except: pass
    return os.getenv("ANTHROPIC_API_KEY","")

def claude(messages, key):
    body = json.dumps({"model": MODEL, "max_tokens": 4096, "system": SYSTEM,
                       "tools": TOOLS, "messages": messages}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"Content-Type":"application/json","x-api-key":key,"anthropic-version":"2023-06-01"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

def run_task(task, key):
    print(f"\n🤖 TASK: {task}\n{'─'*55}")
    messages = [{"role": "user", "content": task}]
    while True:
        resp = claude(messages, key)
        content = resp.get("content", [])
        stop = resp.get("stop_reason")
        for block in content:
            if block.get("type") == "text" and block["text"].strip():
                print(f"\n💬 {block['text']}")
        messages.append({"role": "assistant", "content": content})
        if stop == "end_turn":
            print(f"\n{'─'*55}\n✅ Done\n")
            return
        if stop == "tool_use":
            results = []
            for block in content:
                if block.get("type") == "tool_use":
                    name, inputs, tid = block["name"], block["input"], block["id"]
                    cmd_preview = inputs.get("command", inputs.get("path", inputs.get("summary", "")))[:80]
                    print(f"\n⚙️  {name}({cmd_preview})")
                    result = call_tool(name, inputs)
                    print(f"   ↳ {result[:300]}")
                    results.append({"type":"tool_result","tool_use_id":tid,"content":result[:4000]})
                    if name == "task_complete":
                        print(f"\n{'─'*55}\n✅ {result}\n")
                        return
            messages.append({"role": "user", "content": results})

def main():
    key = load_key()
    if not key:
        print("❌ No ANTHROPIC_API_KEY found in .env")
        sys.exit(1)

    # If task passed as argument, run it and exit
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        run_task(task, key)
        return

    # Otherwise interactive mode
    print("="*55)
    print("  🌉 SlabIQ Bridge — Interactive Mode")
    print("  Type your task and press Enter")
    print("  Ctrl+C to exit")
    print("="*55+"\n")
    while True:
        try:
            task = input("Task: ").strip()
            if task:
                run_task(task, key)
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

if __name__ == "__main__":
    main()
