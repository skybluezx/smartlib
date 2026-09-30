from dataclasses import dataclass
from os import environ
from uuid import UUID


@dataclass(frozen=True)
class Settings:
    database_url: str
    dev_actor_id: UUID
    environment: str
    search_backend: str
    opensearch_url: str
    opensearch_index_alias: str
    graph_backend: str
    hugegraph_url: str
    hugegraph_user: str
    hugegraph_password: str
    hugegraph_graph: str
    s3_endpoint_url: str
    s3_bucket: str
    s3_access_key: str
    s3_secret_key: str
    s3_region: str
    fulltext_max_bytes: int

    @classmethod
    def from_env(cls) -> Settings:
        search_backend = environ.get("SMARTLIB_SEARCH_BACKEND", "postgres")
        if search_backend not in {"postgres", "opensearch"}:
            raise ValueError("SMARTLIB_SEARCH_BACKEND must be postgres or opensearch")
        graph_backend = environ.get("SMARTLIB_GRAPH_BACKEND", "postgres")
        if graph_backend not in {"postgres", "hugegraph"}:
            raise ValueError("SMARTLIB_GRAPH_BACKEND must be postgres or hugegraph")
        return cls(
            database_url=environ.get(
                "SMARTLIB_DATABASE_URL",
                "postgresql://smartlib_api@localhost:5432/smartlib",
            ),
            dev_actor_id=UUID(environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001")),
            environment=environ.get("SMARTLIB_ENVIRONMENT", "development"),
            search_backend=search_backend,
            opensearch_url=environ.get("SMARTLIB_OPENSEARCH_URL", "http://localhost:9200"),
            opensearch_index_alias=environ.get("SMARTLIB_OPENSEARCH_INDEX_ALIAS", "smartlib-knowledge-read"),
            graph_backend=graph_backend,
            hugegraph_url=environ.get("SMARTLIB_HUGEGRAPH_URL", "http://localhost:8080"),
            hugegraph_user=environ.get("SMARTLIB_HUGEGRAPH_USER", "admin"),
            hugegraph_password=environ.get("SMARTLIB_HUGEGRAPH_PASSWORD", ""),
            hugegraph_graph=environ.get("SMARTLIB_HUGEGRAPH_GRAPH", "hugegraph"),
            s3_endpoint_url=environ.get("SMARTLIB_S3_ENDPOINT_URL", "http://localhost:19000"),
            s3_bucket=environ.get("SMARTLIB_S3_BUCKET", "smartlib-publications"),
            s3_access_key=environ.get("SMARTLIB_S3_ACCESS_KEY", ""),
            s3_secret_key=environ.get("SMARTLIB_S3_SECRET_KEY", ""),
            s3_region=environ.get("SMARTLIB_S3_REGION", "us-east-1"),
            fulltext_max_bytes=int(environ.get("SMARTLIB_FULLTEXT_MAX_BYTES", str(100 * 1024 * 1024))),
        )
