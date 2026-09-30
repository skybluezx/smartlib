import argparse
import json
from pathlib import Path

from smartlib_platform.entrypoints.http import app


def main() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    output = repository_root / "packages/api-contracts/openapi/smartlib-platform-v1.json"
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if the live application contract differs")
    args = parser.parse_args()
    content = json.dumps(app.openapi(), ensure_ascii=False, separators=(",", ":")) + "\n"
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != content:
            raise SystemExit("OpenAPI contract is stale; export and regenerate the client before release")
        print("SMARTLIB_OPENAPI_CURRENT")
        return
    output.write_text(content, encoding="utf-8")
    print(f"SMARTLIB_OPENAPI_EXPORTED {output}")


if __name__ == "__main__":
    main()
