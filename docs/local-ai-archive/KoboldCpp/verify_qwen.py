# -*- coding: utf-8 -*-
"""Historical deployment verification: model ID, tok/s, tool calls, Anthropic endpoint."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:5001"

def post(path, payload, timeout=300):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def main():
    # 1) model id
    with urllib.request.urlopen(BASE + "/v1/models", timeout=30) as r:
        models = json.loads(r.read())
    mid = models["data"][0]["id"]
    print(f"1) model id = {mid}")

    # 2) speed
    t0 = time.time()
    r = post("/v1/chat/completions", {
        "model": mid, "temperature": 0.6, "max_tokens": 128,
        "messages": [{"role": "user", "content": "Write a Python function to reverse a string."}],
    })
    dt = time.time() - t0
    ct = r["usage"]["completion_tokens"]
    print(f"2) speed = {ct/max(dt,0.01):.2f} tok/s ({ct} tok in {dt:.1f}s)")

    # 3) tool calls x5 (temperature 0.6 - the historical anti-loop setting)
    tools = [{"type": "function", "function": {"name": "read_file", "description": "Read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]
    cases = ["读取 src/main.py", "读取 package.json", "读取 README.md", "读取 config/settings.json", "读取 src/app.py"]
    ok = 0
    for c in cases:
        r = post("/v1/chat/completions", {
            "model": mid, "temperature": 0.6, "max_tokens": 256, "tools": tools,
            "messages": [{"role": "user", "content": c}],
        })
        m = r["choices"][0]["message"]
        if m.get("tool_calls"):
            tc = m["tool_calls"][0]["function"]
            print(f"   [{c[:12]}] OK -> {tc['name']}({tc['arguments']})")
            ok += 1
        else:
            print(f"   [{c[:12]}] NO TOOL CALL -> {str(m.get('content'))[:80]}")
    print(f"3) tool calls = {ok}/5")

    # 4) Anthropic endpoint (Claude Code direct)
    body = json.dumps({"model": mid, "max_tokens": 64, "temperature": 0.6,
        "messages": [{"role": "user", "content": "Hello"}]}).encode()
    req = urllib.request.Request(BASE + "/v1/messages", data=body,
                                 headers={"Content-Type": "application/json", "x-api-key": "koboldcpp"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        r = json.loads(resp.read())
    print(f"4) anthropic = stop_reason={r.get('stop_reason')}, blocks={[b['type'] for b in r.get('content', [])]}")

if __name__ == "__main__":
    main()
