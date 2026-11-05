import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("server_backup", Path(__file__).resolve().parents[1] / "deploy/server_backup.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeDocker:
    def __init__(self, mqtt="false", fail_copy=False):
        self.calls = []
        self.mqtt = mqtt
        self.fail_copy = fail_copy

    def __call__(self, args):
        self.calls.append(args)
        if args[1] == "compose":
            return "test-app"
        if args[1] == "inspect":
            return json.dumps([{
                "Image": "sha256:test-image",
                "Config": {"Env": ["MQTT_ENABLED=" + self.mqtt], "Labels": {
                    "com.docker.compose.project": "vd10-workflow", "com.docker.compose.service": "app",
                }},
                "State": {"Running": True, "Health": {"Status": "healthy"}},
                "Mounts": [{"Type": "volume", "Destination": "/var/lib/vd10", "Name": "test-data"}],
            }])
        if args[1:3] == ["image", "inspect"]:
            return "1000"
        if args[1:3] == ["image", "save"]:
            Path(args[args.index("-o") + 1]).write_bytes(b"fake-image-for-unit-test")
        if args[1] == "cp":
            if self.fail_copy:
                raise RuntimeError("test copy failure")
            (Path(args[-1]) / "history.jsonl").write_text("{}\n", encoding="utf-8")
        return ""


class ServerBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        (self.project / "deploy").mkdir(parents=True)
        (self.project / "deploy/compose.json").write_text("{}", encoding="utf-8")
        (self.project / "deploy/server.env").write_text("TEST_SETTING=private-test-value\n", encoding="utf-8")
        (self.project / ".venv").mkdir()
        (self.project / ".venv/excluded.txt").write_text("exclude", encoding="utf-8")
        self.space = patch.object(MODULE.shutil, "disk_usage", return_value=type("Disk", (), {"free": 10 * 1024**3})())
        self.space.start()
        self.addCleanup(self.space.stop)

    def test_backup_preserves_config_and_checksums_and_restarts(self):
        runner = FakeDocker()
        result = MODULE.backup(self.project, self.root / "backups", run=runner)
        self.assertGreaterEqual(MODULE.verify(result), 4)
        with tarfile.open(result / "source-and-config.tar.gz") as archive:
            self.assertIn("project/deploy/server.env", archive.getnames())
            self.assertNotIn("project/.venv/excluded.txt", archive.getnames())
        self.assertIn(["docker", "container", "start", "test-app"], runner.calls)
        metadata = json.loads((result / "metadata.json").read_text(encoding="utf-8"))
        self.assertTrue(metadata["includesSecrets"])
        self.assertNotIn("private-test-value", (result / "metadata.json").read_text())

    def test_copy_error_still_restarts_without_complete_marker(self):
        runner = FakeDocker(fail_copy=True)
        with self.assertRaisesRegex(RuntimeError, "copy failure"):
            MODULE.backup(self.project, self.root / "backups", run=runner)
        self.assertIn(["docker", "container", "start", "test-app"], runner.calls)
        self.assertFalse(list((self.root / "backups").glob("*/COMPLETE")))

    def test_mqtt_enabled_refuses_to_stop(self):
        runner = FakeDocker(mqtt="true")
        with self.assertRaisesRegex(ValueError, "MQTT enabled"):
            MODULE.backup(self.project, self.root / "backups", run=runner)
        self.assertFalse(any(call[1:3] == ["container", "stop"] for call in runner.calls))

    def test_checksum_tampering_is_rejected(self):
        result = MODULE.backup(self.project, self.root / "backups", run=FakeDocker())
        (result / "image.tar").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            MODULE.verify(result)

    def test_backup_inside_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            MODULE.backup(self.project, self.project / "backups", run=FakeDocker())


if __name__ == "__main__":
    unittest.main()
