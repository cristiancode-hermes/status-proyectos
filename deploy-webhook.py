#!/usr/bin/env python3
"""Webhook receiver for auto-deploy.

Listens on port 4870 for POST /deploy/landings with a Bearer token.
Verifies token, then git-pulls the repo.
"""

import os
import sys
import json
import subprocess
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("deploy-webhook")

SECRET_FILE = os.path.expanduser("~/.webhook_secret")
DEPLOY_DIR = "/opt/data/landing-pages-refined"

def load_secret():
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if secret:
        return secret.encode()
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE) as f:
            return f.read().strip().encode()
    return None

def verify_auth(auth_header: str, secret: bytes) -> bool:
    if not auth_header or not secret:
        return False
    expected = "Bearer " + secret.decode()
    return auth_header == expected

GH_TOKEN_FILE = "/opt/data/.gh_token"

def git_pull():
    # Use GIT_ASKPASS to authenticate without leaking token in URL
    if os.path.exists(GH_TOKEN_FILE):
        askpass_script = os.path.join(DEPLOY_DIR, ".git", "askpass.sh")
        with open(askpass_script, "w") as f:
            f.write("#!/bin/bash\n")
            f.write(f"cat {GH_TOKEN_FILE}\n")
        os.chmod(askpass_script, 0o700)
        env = {**os.environ, "GIT_ASKPASS": askpass_script, "GIT_TERMINAL_PROMPT": "0"}
    else:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    result = subprocess.run(
        ["git", "pull"],
        cwd=DEPLOY_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        env=env
    )
    # Clean up askpass script
    if os.path.exists(GH_TOKEN_FILE):
        try:
            os.remove(os.path.join(DEPLOY_DIR, ".git", "askpass.sh"))
        except OSError:
            pass
    return result.returncode == 0, result.stdout + result.stderr

class DeployHandler(BaseHTTPRequestHandler):
    secret = load_secret()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"deploy-webhook running\n")

    def do_POST(self):
        if self.path != "/deploy/landings":
            self.send_response(404)
            self.end_headers()
            return

        auth = self.headers.get("Authorization", "")
        if self.secret and not verify_auth(auth, self.secret):
            log.warning("Invalid auth token")
            self.send_response(403)
            self.end_headers()
            return

        json.dumps(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)))))
        success, output = git_pull()
        status = 200 if success else 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok" if success else "error",
            "output": output[:1000]
        }).encode())

    def log_message(self, format, *args):
        log.info(format % args)

def main():
    if not os.path.isdir(DEPLOY_DIR):
        log.error(f"Deploy dir not found: {DEPLOY_DIR}")
        sys.exit(1)

    if not DeployHandler.secret:
        log.warning("No webhook secret configured!")

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4870
    server = HTTPServer(("127.0.0.1", port), DeployHandler)
    log.info(f"Listening on 127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

if __name__ == "__main__":
    main()
