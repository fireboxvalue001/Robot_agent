"""Explicit, offline backup of the current MQTT-disabled staging application."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import uuid


def command(args):
    result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=900)
    return result.stdout.strip()


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def verify(directory):
    directory = Path(directory).resolve(strict=True)
    if not (directory / "COMPLETE").is_file():
        raise ValueError("Backup has no COMPLETE marker; do not use it as a verified backup.")
    hashes = json.loads((directory / "checksums.json").read_text(encoding="utf-8"))
    if not hashes:
        raise ValueError("Backup checksum list is empty.")
    for name, expected in hashes.items():
        path = directory / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(directory):
            raise ValueError("Unsafe backup path.")
        if digest(path) != expected:
            raise ValueError("Backup checksum mismatch.")
    return len(hashes)


def backup(project, backup_root, run=command, health_timeout=90):
    project = Path(project).resolve(strict=True)
    config = project / "deploy/compose.json"
    settings = project / "deploy/server.env"
    if not config.is_file() or not settings.is_file() or settings.is_symlink():
        raise ValueError("Expected a staging project with a regular server.env file.")
    compose = ["docker", "compose", "-f", str(config)]
    container = run(compose + ["ps", "-q", "app"])
    if not container or len(container.splitlines()) != 1:
        raise ValueError("Expected exactly one running app container.")
    info = json.loads(run(["docker", "inspect", container]))[0]
    labels = info["Config"].get("Labels", {})
    if labels.get("com.docker.compose.project") != "vd10-workflow" or labels.get("com.docker.compose.service") != "app":
        raise ValueError("Container is not the expected staging application.")
    env = dict(item.split("=", 1) for item in info["Config"].get("Env", []) if "=" in item)
    if env.get("MQTT_ENABLED", "").lower() != "false":
        raise ValueError("Refusing to stop an application with MQTT enabled.")
    if not info["State"].get("Running") or info["State"].get("Health", {}).get("Status") != "healthy":
        raise ValueError("Application must be running and healthy before backup.")
    mounts = [mount for mount in info.get("Mounts", []) if mount.get("Destination") == "/var/lib/vd10"]
    if len(mounts) != 1 or mounts[0].get("Type") != "volume":
        raise ValueError("Expected the application named data volume.")
    image = info["Image"]
    size = int(run(["docker", "image", "inspect", "--format", "{{.Size}}", image]))
    root = Path(backup_root).absolute()
    if root.is_symlink():
        raise ValueError("Backup root cannot be a symlink.")
    root = root.resolve()
    if root == project or root.is_relative_to(project):
        raise ValueError("Keep backups outside the deployment source directory.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    if shutil.disk_usage(root).free < max(3 * 1024**3, 2 * size):
        raise ValueError("Insufficient spare disk for a complete image backup.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = root / stamp
    directory.mkdir(mode=0o700)
    tag = "checkpoint-" + stamp.lower()
    checkpoint = "vd10-workflow:" + tag
    run(["docker", "image", "tag", image, checkpoint])
    run(["docker", "image", "save", "-o", str(directory / "image.tar"), checkpoint])

    def source_filter(member):
        if set(Path(member.name).parts) & {".git", ".venv", "node_modules", "__pycache__"}:
            return None
        return member

    # Source/config are read-only to the application; stop it before copying data.
    with tarfile.open(directory / "source-and-config.tar.gz", "w:gz", dereference=False) as archive:
        archive.add(project, arcname="project", filter=source_filter)
    data = directory / "app-data"
    data.mkdir(mode=0o700)
    try:
        run(["docker", "container", "stop", "--time", "30", container])
        run(["docker", "cp", "-a", f"{container}:/var/lib/vd10/.", str(data)])
    finally:
        # Restart the same container, not a possibly changed Compose definition.
        run(["docker", "container", "start", container])
    deadline = time.monotonic() + health_timeout
    while True:
        current = json.loads(run(["docker", "inspect", container]))[0]
        if current["State"].get("Running") and current["State"].get("Health", {}).get("Status") == "healthy":
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Application did not recover health; backup is incomplete. Check container status.")
        time.sleep(1)
    record = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "imageId": image,
        "checkpointImage": checkpoint,
        "releaseTag": tag,
        "volume": mounts[0]["Name"],
        "mqttEnabled": False,
        "includesSecrets": True,
        "limitations": "No in-memory task state; no whole-server/SSH/Docker daemon backup; no offsite copy or restore drill.",
    }
    (directory / "metadata.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    hashes = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Data contains a symlink; backup requires manual review.")
        if path.is_file():
            hashes[path.relative_to(directory).as_posix()] = digest(path)
    (directory / "checksums.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    (directory / "COMPLETE").write_text("Staging backup and service health checks passed.\n", encoding="utf-8")
    verify(directory)
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--project")
    operation.add_argument("--verify")
    parser.add_argument("--backup-root", default="/var/backups/vd10")
    parser.add_argument("--confirm-stop", action="store_true")
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("Run on the Linux SERVER with sudo, not on the Windows development computer.")
    os.umask(0o077)
    if args.verify:
        print("Backup files verified:", verify(args.verify))
        return
    if not args.confirm_stop:
        parser.error("Finish recording/planning and add --confirm-stop to allow a brief application stop.")
    try:
        directory = backup(args.project, args.backup_root)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("BACKUP NOT CONFIRMED:", str(exc), file=sys.stderr)
        print("Do not delete partial backups. Check the application container state before retrying.", file=sys.stderr)
        raise SystemExit(1)
    print("Backup completed:", directory)
    print("Contains real credentials. Keep private; do not upload or paste backup contents.")
    print("The same application container was restarted and is healthy. MQTT remains disabled.")


if __name__ == "__main__":
    main()
