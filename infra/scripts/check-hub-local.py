"""Run rollback-only DB acceptance using the running local API's environment."""
import json
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--script', choices=['check_knowledge_hub_workbench.py', 'check_leadership_workspace.py', 'check_library_work.py', 'check_hub_skill.py'], default='check_knowledge_hub_workbench.py')
script = parser.parse_args().script
root = Path(__file__).resolve().parents[2]
api = json.loads(subprocess.check_output(["docker", "inspect", "smartlib-platform-api-1"]))[0]
network = next(iter(api["NetworkSettings"]["Networks"]))
with tempfile.TemporaryDirectory(prefix="smartlib-hub-check-", dir="/private/tmp") as directory:
    env_path = Path(directory) / "runtime.env"
    env_path.write_text("\n".join(value for value in api["Config"]["Env"] if value.startswith("SMARTLIB_")) + "\n")
    os.chmod(env_path, 0o600)
    subprocess.run([
        "docker", "run", "--rm", "--network", network,
        "--env-file", str(env_path), "-e", "PYTHONPATH=/work/src",
        "-v", str(root / "apps/platform-api") + ":/work:ro", "-w", "/work",
        "-v", str(root / "skills") + ":/skills:ro",
        api["Config"]["Image"], "python", "scripts/" + script,
    ], check=True)
