"""Rebuild ONLY the local API/web, retaining live API environment. No data services touched."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
containers = json.loads(subprocess.check_output([
    "docker", "inspect", "smartlib-platform-api-1", "smartlib-web-1"
]))
services = {}
for service, container in zip(["platform-api", "web"], containers, strict=True):
    environment = dict(value.split("=", 1) for value in container["Config"]["Env"])
    services[service] = {"environment": {key: value.replace("$", "$$") for key, value in environment.items()},
                         "image": container["Config"]["Image"]}
with tempfile.TemporaryDirectory(prefix="smartlib-hub-deploy-", dir="/private/tmp") as directory:
    override = Path(directory) / "runtime.json"
    override.write_text(json.dumps({"services": services}))
    os.chmod(override, 0o600)
    subprocess.run([
        "docker", "compose", "--env-file", str(root / "infra/compose/.env.local"),
        "-f", str(root / "infra/compose/compose.yaml"), "-f", str(override),
        "up", "-d", "--no-deps", "--build", "platform-api", "web",
    ], check=True, cwd=root)
