"""Read-only HTTP checks; never starts MQTT, invokes AI, or submits a task."""
import argparse
import json
import urllib.error
import urllib.request


def verify(base_url):
    base_url = base_url.rstrip("/")

    def read(path):
        with urllib.request.urlopen(base_url + path, timeout=10) as response:
            return response.read()

    health = json.loads(read("/api/health"))
    if health.get("status") != "ok" or health.get("mqtt", {}).get("enabled") is not False:
        raise RuntimeError("Health check failed, or MQTT is not disabled for this staging check.")
    library = json.loads(read("/api/v1/capabilities/meta-operations"))
    if not library.get("metaOperations"):
        raise RuntimeError("Capability library is missing.")
    if b"<html" not in read("/").lower():
        raise RuntimeError("Frontend HTML is missing.")
    for path in ("/app.js", "/voice-input.js", "/extraction-flow.js", "/styles.css"):
        if not read(path):
            raise RuntimeError("Frontend asset is empty.")
    for path in ("/.env", "/backend/.env", "/deploy/server.env", "/data/mqtt_history/test.jsonl"):
        try:
            read(path)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        else:
            raise RuntimeError("A private path was unexpectedly served.")
    return {"status": "passed", "mqttEnabled": False, "operations": len(library["metaOperations"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8877")
    args = parser.parse_args()
    print(json.dumps(verify(args.base_url)))
