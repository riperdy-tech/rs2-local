"""A stand-in for llama-server as a REAL process (it can be killed, and it can leave a child behind), for the lifecycle tests
of llamacpp_server.py. It prints the log lines the lifecycle checks, answers GET /health (503 while "loading") and
POST /v1/chat/completions, and does nothing else. No GPU, no model.

  python mock_llama_server_process.py --port N [--ready-after S] [--delay S] [--n-ctx 98304] [--n-max 15]
                                      [--child-pid-file F] [--exit-code C]
--exit-code C   exit at once with code C (a server that dies before it is ready)
--child-pid-file F   start a sleeping grandchild and write its PID to F (the tree that taskkill /T must take down)
--delay S       answer each completion after S seconds (to be killed mid-request)"""
import argparse
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--ready-after", type=float, default=0.0)
ap.add_argument("--delay", type=float, default=0.0)
ap.add_argument("--n-ctx", type=int, default=98304)
ap.add_argument("--n-max", type=int, default=15)
ap.add_argument("--child-pid-file")
ap.add_argument("--exit-code", type=int)
a = ap.parse_args()

if a.exit_code is not None:
    print("srv load_model: failed to load model", flush=True)
    sys.exit(a.exit_code)

print(f"srv    load_model: initializing, n_slots = 1, n_ctx_slot = {a.n_ctx}, kv_unified = 'false'", flush=True)
print(f"common_speculative_impl_draft_dflash: - n_max={a.n_max}, n_min=0, p_min=0.00", flush=True)
if a.child_pid_file:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    open(a.child_pid_file, "w").write(str(child.pid))
started = time.time()


class H(BaseHTTPRequestHandler):
    def _send(self, status, obj):
        data = json.dumps(obj).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def do_GET(self):
        if self.path == "/health":
            if time.time() - started >= a.ready_after:
                self._send(200, {"status": "ok"})
            else:
                self._send(503, {"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}})
        else:
            self._send(404, {})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        time.sleep(a.delay)
        self._send(200, {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                         "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                         "timings": {"prompt_ms": 5.0, "predicted_ms": 5.0, "predicted_n": 2, "prompt_n": 10,
                                     "draft_n": 4, "draft_n_accepted": 1}})

    def log_message(self, *x):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
srv.daemon_threads = True
print("srv  llama_server: model loaded", flush=True)
print(f"srv  llama_server: listening on http://127.0.0.1:{a.port}", flush=True)
srv.serve_forever()
