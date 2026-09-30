#!/bin/sh
set -eu

opensearch_url="${SMARTLIB_OPENSEARCH_URL:-http://opensearch:9200}"
template_path="/smartlib-opensearch/index-template-v1.json"

curl --fail --silent --show-error \
  --request PUT \
  --header 'Content-Type: application/json' \
  --data-binary "@$template_path" \
  "$opensearch_url/_index_template/smartlib-knowledge-v1"

# A rebuild may already have replaced the initial index. Never attach an empty
# initial index to existing aliases merely because the original index is gone.
if ! curl --fail --silent "$opensearch_url/_alias/smartlib-knowledge-write" >/dev/null; then
  curl --fail --silent --show-error \
    --request PUT \
    --header 'Content-Type: application/json' \
    --data-binary '{"aliases":{"smartlib-knowledge-read":{},"smartlib-knowledge-write":{"is_write_index":true}}}' \
    "$opensearch_url/smartlib-knowledge-v1-000001"
fi

curl --fail --silent "$opensearch_url/_cluster/health?wait_for_status=yellow&timeout=60s" >/dev/null
echo "SMARTLIB_OPENSEARCH_BOOTSTRAP_OK"
