"""Use the same preflight/commit HTTP flow as the UI, only against local deployment."""

import json
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[3]
out = root / "outputs/library-work-20260930"
file = out / "馆务模拟数据.zip"
with httpx.Client(base_url="http://127.0.0.1:18080/api/v1/knowledge-hub/library-work", timeout=120) as client:

    def read(path):
        r = client.get(path)
        r.raise_for_status()
        return r.json()

    before = read("/overview?mode=real")["summary"]["records"]
    with file.open("rb") as stream:
        response = client.post(
            "/preview", data={"mode": "demo"}, files={"file": (file.name, stream, "application/zip")}
        )
    response.raise_for_status()
    preview = response.json()
    assert preview["count"] == 300 and not preview["errors"]
    result = client.post(
        "/batches/" + preview["id"] + "/commit",
        json={
            "confirm": True,
            "reason": "依据25类原表字段生成300条独立模拟事项，用于馆务功能演示，不含真实业务记录",
        },
    )
    result.raise_for_status()
    result = result.json()
    repeated = client.post(
        "/batches/" + preview["id"] + "/commit",
        json={"confirm": True, "reason": "核验重复提交不产生重复事项"},
    )
    repeated.raise_for_status()
    assert repeated.json()["reused"]
    summary = read("/overview?mode=demo")
    assert summary["summary"]["records"] == 300
    assert summary["summary"]["categories"] == 25
    assert read("/overview?mode=real")["summary"]["records"] == before
    rows = read("/records?mode=demo&category=reader_training")
    assert rows["total"] == 12
    record = read("/records/" + rows["items"][0]["id"])
    assert record["mode"] == "demo" and len(record["history"]) == 1
    receipt = {
        "batch_id": preview["id"],
        "commit": result,
        "formal_records_before": before,
        "formal_records_after": before,
        "demo_summary": summary["summary"],
        "categories": summary["categories"],
        "years": summary["years"],
        "idempotent_retry": True,
        "source_row_drilldown": True,
        "endpoint": "local:18080",
        "remote_deployed": False,
    }
    (out / "import-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in receipt.items() if key not in ("categories", "years")},
            ensure_ascii=False,
        )
    )
