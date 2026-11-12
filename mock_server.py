"""Tiny scripted OpenAI-compatible server for testing Kit + Corvi without a real model."""
import json, sys, http.server, time

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = json.dumps({"data": [{"id": "mock-coder"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body["messages"]
        last_user = [m for m in msgs if m["role"] == "user"][-1]["content"].lower()
        tools_done = [m for m in msgs[::-1] if m["role"] == "user"][0]
        after = msgs[msgs.index(tools_done) + 1:]
        n_tool = sum(1 for m in after if m["role"] == "tool")
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        def tool(name, args):
            return [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c%d" % n_tool, "function": {"name": name, "arguments": json.dumps(args)}}]}}]}]
        def say(t):
            return [{"choices": [{"delta": {"content": w}}]} for w in (t.split(" ")[0] + " ", *[x + " " for x in t.split(" ")[1:]])]
        script = {
            "read": [tool("read_file", {"path": "README.md"}), say("I read the file. It looks great!")],
            "fail": [tool("run_bash", {"command": "ls /definitely/not/here"}), say("That command failed because the folder is missing.")],
            "tests": [tool("run_bash", {"command": "pytest -q; true"}), say("Tests ran.")],
            "slow": [tool("run_bash", {"command": "sleep 3 && echo done"}), say("The slow command finished.")],
            "build": [tool("run_bash", {"command": "make build 2>&1; echo built"}), say("Built it.")],
            "write": [tool("write_file", {"path": "hello.txt", "content": "hi from corvi\n"}), say("I wrote hello.txt.")],
        }
        key = next((k for k in ("write", "tests", "build", "slow", "read", "fail") if k in last_user), None)
        steps = script.get(key, [say("Hello! I'm Corvi. How can I help you code today?")])
        chunks = steps[n_tool] if n_tool < len(steps) else say("Done!")
        for c in chunks:
            self.wfile.write(("data: " + json.dumps(c) + "\n\n").encode()); self.wfile.flush(); time.sleep(0.03)
        self.wfile.write(b"data: [DONE]\n\n")

if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 11999), H).serve_forever()
