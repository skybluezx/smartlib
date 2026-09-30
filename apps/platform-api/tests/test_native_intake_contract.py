from smartlib_platform.entrypoints.http import app


def test_current_intake_contract_has_no_retired_routes_or_id_aliases():
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/ingestion/publications" in paths
    assert "/api/v1/ingestion/publications/file" in paths
    assert "/api/v1/publications/intake/{record_id}" in paths
    assert not any("/knowledge-hub/publication-imports" in p for p in paths)
    assert not any("/knowledge-hub/publication-verifications" in p for p in paths)
    models = schema["components"]["schemas"]
    assert "batch_id" in models["PublicationImportResult"]["required"]
    assert "record_id" in models["PublicationVerificationDetail"]["required"]
    for model in models.values():
        assert "import_item_id" not in model.get("properties", {})
        assert "import_batch_id" not in model.get("properties", {})
