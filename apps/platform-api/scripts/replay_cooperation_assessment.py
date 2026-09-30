"""Recompute a downloaded cooperation evidence JSON without querying live databases."""

import argparse
import json
from pathlib import Path

from smartlib_platform.graph_analytics.cooperation import METHOD, assess_cooperation

parser = argparse.ArgumentParser()
parser.add_argument("snapshot", type=Path)
args = parser.parse_args()
export = json.loads(args.snapshot.read_text())
a = export.get("assessment", export.get("people_collaboration", {}).get("assessment"))
if not a or a["method_version"] != METHOD:
    raise SystemExit("Unsupported snapshot method version")
publications = {}
organizations = {}
for p in a["publications"]:
    publications[p["publication_id"]] = {
        "title": p["title"],
        "people": {n["id"]: n["name"] for n in p["authors"]},
        "author_evidence": {r["relation_id"]: r for r in p.get("author_evidence", [])},
    }
    organizations.update({n["id"]: n["organizations"] for n in p["authors"]})
replayed_model = assess_cooperation(publications, organizations, a["scope_publication_ids"], entity_type=a.get("entity_type", "person"), aggregation_context=a.get("aggregation_context"))
if a.get("metric_input_hash"):
    from smartlib_platform.graph_analytics.cooperation_metrics import enrich_assessment
    enrich_assessment(replayed_model, a["metric_context"], a["metric_inputs"])
    if replayed_model.metric_input_hash != a["metric_input_hash"]:
        raise SystemExit("Mismatch: metric input fingerprint")
replayed = replayed_model.model_dump()
for key in ("library_version", "parameters", "input_hash", "communities", "sensitivity", "modularity"):
    if replayed[key] != a[key]:
        raise SystemExit(f"Mismatch: {key}; check software version or modified evidence")
print("MATCH: input, parameters, partition, metrics and sensitivity reproduced")
