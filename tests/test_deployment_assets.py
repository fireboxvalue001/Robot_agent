import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
import urllib.error

from deploy.probe import verify


ROOT = Path(__file__).resolve().parents[1]


class DeploymentAssetTests(unittest.TestCase):
    def test_staging_is_loopback_only_and_mqtt_is_forced_off(self):
        config = json.loads((ROOT / "deploy/compose.json").read_text(encoding="utf-8"))
        app = config["services"]["app"]
        self.assertEqual(app["ports"], ["127.0.0.1:8877:8877"])
        self.assertEqual(app["environment"]["MQTT_ENABLED"], "false")
        self.assertTrue(app["read_only"])
        self.assertEqual(app["volumes"], ["app-data:/var/lib/vd10"])
        self.assertEqual(app["cap_drop"], ["ALL"])
        self.assertIn("server.env", app["env_file"][0])

    def test_https_is_separate_and_access_fails_closed(self):
        config = json.loads((ROOT / "deploy/compose.https.json").read_text(encoding="utf-8"))
        caddy = config["services"]["caddy"]
        self.assertEqual(caddy["ports"], ["80:80", "443:443"])
        self.assertIn(":?", caddy["environment"]["VD10_DOMAIN"])
        access = (ROOT / "deploy/access.caddy.example").read_text(encoding="utf-8")
        self.assertIn('respond "Internal access is not configured." 403', access)
        self.assertIn("/etc/caddy/access.caddy", (ROOT / "deploy/Caddyfile").read_text())

    def test_image_does_not_copy_repo_or_enable_reload(self):
        dockerfile = (ROOT / "deploy/Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("COPY . ", dockerfile)
        self.assertNotIn("--reload", dockerfile)
        self.assertIn('"--workers", "1"', dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        ignores = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("**/.env", ignores)
        self.assertIn("data/mqtt_history/", ignores)
        lock = (ROOT / "deploy/requirements.lock").read_text(encoding="utf-8")
        for line in lock.splitlines():
            if line and not line.startswith("#"):
                self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[0-9][A-Za-z0-9_.-]*$")

    def test_local_http_startup_without_cloud_or_mqtt(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ)
        env.update({
            "MQTT_ENABLED": "false",
            "TENCENTCLOUD_SECRET_ID": "",
            "TENCENTCLOUD_SECRET_KEY": "",
            "TENCENTCLOUD_APP_ID": "",
            "DEEPSEEK_API_KEY": "",
            "DOCUMENT_INTENT_API_KEY": "",
            "DASHSCOPE_API_KEY": "",
        })
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                self.assertIsNone(process.poll(), "Local staging process exited before its health check.")
                try:
                    result = verify(f"http://127.0.0.1:{port}")
                    break
                except urllib.error.URLError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["operations"], 101)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def test_pip_network_options_are_build_scoped(self):
        dockerfile = (ROOT / "deploy/Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG PIP_INDEX_URL=https://pypi.org/simple", dockerfile)
        self.assertIn("ARG PIP_TIMEOUT=120", dockerfile)
        self.assertIn("ARG PIP_RETRIES=5", dockerfile)
        self.assertIn('--index-url "$PIP_INDEX_URL"', dockerfile)
        self.assertIn('--timeout "$PIP_TIMEOUT" --retries "$PIP_RETRIES"', dockerfile)
        self.assertNotIn("--trusted-host", dockerfile)
        self.assertNotIn("--extra-index-url", dockerfile)
        self.assertNotIn("pip config set", dockerfile)


if __name__ == "__main__":
    unittest.main()
