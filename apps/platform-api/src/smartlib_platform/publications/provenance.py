"""Publication-specific relation creation; generic relation commands stay domain-neutral."""

from uuid import UUID

from smartlib_platform.foundation.database import DbConnection
from smartlib_platform.relations.models import RelationCreate, RelationView
from smartlib_platform.relations.service import create_relation


class PublicationRelationCreate(RelationCreate):
    publication_authorship_id: UUID


class PublicationRelationView(RelationView):
    publication_authorship_id: UUID


def create_publication_relation(
    connection: DbConnection, command: PublicationRelationCreate, actor_id: UUID, trace_id: str
) -> PublicationRelationView:
    relation = create_relation(
        connection,
        RelationCreate.model_validate(command.model_dump(exclude={"publication_authorship_id"})),
        actor_id,
        trace_id,
    )
    connection.execute(
        """INSERT INTO smartlib.publication_relation_provenance(relation_id,publication_authorship_id)
           VALUES (%s,%s)""",
        (relation.relation_id, command.publication_authorship_id),
    )
    return PublicationRelationView(
        **relation.model_dump(), publication_authorship_id=command.publication_authorship_id
    )
