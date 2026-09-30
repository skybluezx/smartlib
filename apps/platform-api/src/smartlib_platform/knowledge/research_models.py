"""Public scoped research analysis contract, independent of governance UI."""
from pydantic import BaseModel, Field
from uuid import UUID

class ScopedResearchAnalysis(BaseModel):
    publication_ids: list[UUID] = Field(max_length=100000)
    scheme: str = Field(default='NSFC_APPLICATION_CODE', max_length=100)
    scheme_version: str | None = Field(default=None, max_length=100)
    collaboration_institution_id: UUID | None = None

class ResearchDirectionCount(BaseModel):
    version: str
    code: str
    name: str
    count: int
    papers: list[str]

class ResearchTrend(ResearchDirectionCount):
    year: int | None

class ResearchIntersection(BaseModel):
    a: str
    b: str
    version: str
    count: int
    papers: list[str]

class SharedResearchDirection(BaseModel):
    version: str
    code: str
    name: str

class CollaborationCandidate(BaseModel):
    a: str
    b: str
    a_name: str
    b_name: str
    shared: list[SharedResearchDirection]
    a_papers: list[str]
    b_papers: list[str]
    note: str

class ScopedResearchResult(BaseModel):
    papers: int
    classified: int
    directions: list[ResearchDirectionCount]
    trends: list[ResearchTrend]
    intersections: list[ResearchIntersection]
    collaboration: list[CollaborationCandidate]
    paper_titles: dict[str, str]
    note: str
