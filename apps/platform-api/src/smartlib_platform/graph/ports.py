from typing import Protocol
from uuid import UUID

from .models import (
    AdapterNeighborhoodResult,
    AdapterPathResult,
    AdapterRelationExplanation,
    GraphAccessContext,
    NeighborhoodCommand,
    PathCommand,
)


class GraphPort(Protocol):
    def neighborhood(
        self, command: NeighborhoodCommand, access: GraphAccessContext
    ) -> AdapterNeighborhoodResult: ...

    def find_paths(self, command: PathCommand, access: GraphAccessContext) -> AdapterPathResult: ...

    def explain_relation(
        self, relation_id: UUID, access: GraphAccessContext
    ) -> AdapterRelationExplanation | None: ...
