from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .disciplines import DisciplineWorkspace


class AnalysisCoverage(BaseModel):
    publications: int = Field(ge=0)
    publications_with_authors: int = Field(ge=0)
    publications_with_affiliations: int = Field(ge=0)
    publications_with_disciplines: int = Field(ge=0)
    graph_backend: str
    aggregation_source: str = "authoritative_relation_records"
    generated_at: datetime


class AnalysisScopeOption(BaseModel):
    object_id: UUID
    name: str
    publication_count: int = Field(ge=0)


class GraphAnalysisScopeOptions(BaseModel):
    minimum_year: int | None = None
    maximum_year: int | None = None
    project_kinds: list[AnalysisScopeOption] = Field(default_factory=list)
    organizations: list[AnalysisScopeOption] = Field(default_factory=list)
    scholars: list[AnalysisScopeOption] = Field(default_factory=list)


class AppliedAnalysisScope(BaseModel):
    start_year: int | None = None
    end_year: int | None = None
    project_kind_ids: list[UUID] = Field(default_factory=list)
    organization_ids: list[UUID] = Field(default_factory=list)
    scholar_ids: list[UUID] = Field(default_factory=list)
    custom_scope_id: UUID | None = None
    custom_scope_name: str | None = None
    publication_count: int = Field(ge=0)


class CustomGraphScopeQuery(BaseModel):
    graph_query: str = Field(min_length=1, max_length=4000)


class CustomGraphScopeCreate(CustomGraphScopeQuery):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)


class InstitutionGroup(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    member_ids: list[UUID] = Field(min_length=1, max_length=500)


class InstitutionAnalysisSettings(BaseModel):
    mode: Literal["root", "internal", "expanded"] = "root"
    root_ids: list[UUID] = Field(default_factory=list, max_length=100)
    groups: list[InstitutionGroup] = Field(default_factory=list, max_length=100)


AnalysisModule = Literal['journals', 'funding', 'project_journal_metrics', 'disciplines', 'people_collaboration', 'institution_collaboration', 'collaboration_outcomes']


class CustomGraphAnalyticsCommand(CustomGraphScopeQuery):
    selected_module: AnalysisModule | None = None
    institution_settings: str | None = Field(default=None, max_length=30000)
    minimum_publication_count: int = Field(default=2, ge=1, le=20)
    edge_limit: int = Field(default=120, ge=1)
    people_focus_id: UUID | None = None
    people_organization_id: UUID | None = None
    people_include_external: bool = False
    start_year: int | None = Field(default=None, ge=1500, le=2200)
    end_year: int | None = Field(default=None, ge=1500, le=2200)
    project_kind_ids: list[UUID] = Field(default_factory=list)
    organization_ids: list[UUID] = Field(default_factory=list)
    scholar_ids: list[UUID] = Field(default_factory=list)


class CustomGraphScopePublication(BaseModel):
    object_id: UUID
    title: str
    publication_year: int | None = None
    journal_name: str | None = None


class CustomGraphScopeJournal(BaseModel):
    object_id: str
    name: str
    publication_count: int = Field(ge=0)


class CustomGraphScopePreview(BaseModel):
    query_hash: str
    publication_count: int = Field(ge=0)
    publications_with_authors: int = Field(ge=0)
    publications_with_affiliations: int = Field(ge=0)
    minimum_year: int | None = None
    maximum_year: int | None = None
    top_journals: list[CustomGraphScopeJournal] = Field(default_factory=list)
    sample_publications: list[CustomGraphScopePublication] = Field(default_factory=list)
    truncated: bool = False
    took_ms: float = Field(ge=0)


class SavedCustomGraphScope(BaseModel):
    scope_id: UUID
    name: str
    description: str | None = None
    query_language: Literal["cypher"] = "cypher"
    graph_query: str
    last_result_count: int | None = Field(default=None, ge=0)
    last_executed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FundingProjectItem(BaseModel):
    object_id: str
    name: str
    kind_name: str
    grant_number: str | None = None


class FundingKindItem(BaseModel):
    object_id: str
    name: str
    project_count: int = Field(ge=0)
    publication_count: int = Field(ge=0)


class FundingShare(BaseModel):
    kinds: list[FundingKindItem] = Field(default_factory=list)
    projects: list[FundingProjectItem] = Field(default_factory=list)
    object_id: str
    name: str
    funding_agency: str | None = None
    linked_project_count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)


class FundingCandidateShare(BaseModel):
    projects: list[FundingProjectItem] = Field(default_factory=list)
    object_id: str
    name: str
    relation_count: int = Field(ge=0)
    linked_item_count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)
    average_confidence: float = Field(ge=0, le=1)
    review_state: Literal["pending", "approved", "mixed"] = "pending"


class FundingAnalysis(BaseModel):
    category_shares: list[FundingShare] = Field(default_factory=list)
    verified_programs: list[FundingShare]
    verified_project_links: int = Field(ge=0)
    candidate_programs: list[FundingCandidateShare]
    pending_program_relation_count: int = Field(ge=0)
    pending_grant_relation_count: int = Field(ge=0)
    pending_program_candidate_count: int = Field(ge=0)
    pending_grant_candidate_count: int = Field(ge=0)
    pending_project_kind_count: int = Field(default=0, ge=0)
    included_project_kind_count: int = Field(default=0, ge=0)
    pending_relation_count: int = Field(ge=0)
    pending_candidate_count: int = Field(ge=0)
    scope_note: str


class EvidencePublication(BaseModel):
    object_id: str
    title: str


class CollaborationNode(BaseModel):
    object_id: str
    name: str
    node_type: Literal["person", "organization"]
    publication_count: int = Field(ge=0)
    group_key: str | None = None
    community_id: int | None = None
    organizations: dict[str, str] = Field(default_factory=dict)


class CollaborationEdge(BaseModel):
    edge_id: str
    source_id: str
    target_id: str
    publication_count: int = Field(ge=1)
    evidence_publications: list[EvidencePublication]
    collaboration_kind: str | None = None
    highlighted: bool = False


class CommunityMetric(BaseModel):
    code: str
    label: str
    publication_ids: list[str]
    missing_publication_ids: list[str]
    count: int
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None
    total: float | None = None
    above_reference_count: int | None = None
    reference: float | None = None


class CommunityCenter(BaseModel):
    person_id: str
    roles: list[str]
    internal_degree: int
    internal_strength: float
    betweenness: float


class CommunityQuartiles(BaseModel):
    publication_ids: list[str]
    missing_publication_ids: list[str]
    count: int
    paper_equivalents: dict[str, float]
    shares: dict[str, float | None]


class CommunityFundingGroup(BaseModel):
    key: str
    basis: Literal['funded', 'representative']
    category_label: str | None = None
    object_id: str | None = None
    name: str
    publication_ids: list[str]
    project_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)


class CommunityDirection(BaseModel):
    key: str
    object_id: str
    name: str
    scheme: str
    version: str
    code: str
    publication_ids: list[str]
    primary_publication_ids: list[str]
    secondary_publication_ids: list[str]
    relation_ids: list[str] = Field(default_factory=list)


class CommunityResearchCross(BaseModel):
    funding_key: str
    direction_key: str
    publication_ids: list[str]


class CommunityResearch(BaseModel):
    method_version: str = 'community-funding-directions-v2'
    input_hash: str
    funding: list[CommunityFundingGroup]
    directions: list[CommunityDirection]
    intersections: list[CommunityResearchCross]
    projects: dict[str, str]
    funded_publication_ids: list[str]
    representative_publication_ids: list[str]
    unlinked_publication_ids: list[str]
    unclassified_publication_ids: list[str]


class CooperationCommunity(BaseModel):
    community_id: int
    member_ids: list[str]
    publication_ids: list[str]
    internal_edge_count: int
    external_edge_count: int
    density: float
    internal_weight_share: float | None
    connected_components: int
    seed_stability: float
    centers: list[CommunityCenter] = Field(default_factory=list)
    member_center_metrics: list[CommunityCenter] = Field(default_factory=list)
    centers_method: str = 'top-decile-v1'
    metrics: list[CommunityMetric] = Field(default_factory=list)
    quartiles: dict[str, CommunityQuartiles] = Field(default_factory=dict)
    research: CommunityResearch | None = None


class CooperationAssessment(BaseModel):
    aggregation_context: dict[str, Any] = Field(default_factory=dict)
    entity_type: Literal["person", "organization"] = "person"
    method_version: str
    library_version: str
    input_hash: str
    parameters: dict[str, str | int | float]
    scope_publication_ids: list[str]
    missing_author_publication_ids: list[str]
    node_count: int
    edge_count: int
    isolated_node_count: int
    connected_component_count: int
    modularity: float | None
    sensitivity: list[dict[str, str | int | float]]
    communities: list[CooperationCommunity]
    metric_context: dict[str, Any] = Field(default_factory=dict)
    metric_inputs: list[dict[str, Any]] = Field(default_factory=list)
    metric_input_hash: str | None = None
    # Frozen public analytical inputs, no credentials or internal review fields.
    publications: list[dict[str, Any]]
    warnings: list[str]


class CollaborationNetwork(BaseModel):
    institution_options: list[dict[str, Any]] = Field(default_factory=list)
    aggregation_context: dict[str, Any] = Field(default_factory=dict)
    exploration_edges: list[CollaborationEdge] = Field(default_factory=list)
    assessment: CooperationAssessment | None = None
    directory: list[CollaborationNode] = Field(default_factory=list)
    scope_node_count: int = Field(default=0, ge=0)
    matched_node_count: int = Field(default=0, ge=0)
    matched_edge_count: int = Field(default=0, ge=0)
    nodes: list[CollaborationNode]
    edges: list[CollaborationEdge]
    total_node_count: int = Field(ge=0)
    total_edge_count: int = Field(ge=0)
    displayed_edge_count: int = Field(ge=0)
    minimum_publication_count: int = Field(ge=1)
    truncated: bool
    metric_note: str


class DisciplineShare(BaseModel):
    object_id: str
    scheme: str
    code: str | None
    name: str
    level: int | None
    primary_publications: int = Field(ge=0)
    secondary_publications: int = Field(ge=0)
    publication_count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)


class DisciplineAnalysis(BaseModel):
    workspace: DisciplineWorkspace | None = None
    broad_disciplines: list[DisciplineShare]
    nsfc_directions: list[DisciplineShare]
    gbt_directions: list[DisciplineShare]
    classified_publications: int = Field(ge=0)
    primary_relation_count: int = Field(ge=0)
    secondary_relation_count: int = Field(ge=0)
    review_state: str
    scope_note: str


class JournalShare(BaseModel):
    object_id: str
    name: str
    publication_count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)


class QuartileShare(BaseModel):
    quartile: Literal["Q1", "Q2", "Q3", "Q4"]
    paper_equivalents: float = Field(ge=0)
    share: float = Field(ge=0, le=1)


class ImpactFactorSummary(BaseModel):
    matched_publications: int = Field(ge=0)
    mean: float | None = None
    median: float | None = None
    minimum: float | None = None
    maximum: float | None = None


class PublicationMetricAggregate(BaseModel):
    code: str
    label: str
    semantic_level: Literal["publication", "journal_context", "normalization_baseline"]
    unit: str
    aggregation_rule: str
    definition: str
    covered_publications: int = Field(ge=0)
    missing_publications: int = Field(ge=0)
    mean: float | None = None
    median: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    total: float | None = None
    reference: float | None = None
    above_reference_count: int | None = Field(default=None, ge=0)


class InCitesPublicationMetric(BaseModel):
    publication_id: str
    title: str
    publication_year: int | None = None
    journal_name: str | None = None
    source_document_type: str | None = None
    source_research_areas: str | None = None
    source_collaboration_type: str | None = None
    metric_values: dict[str, float | None] = Field(default_factory=dict)


class InCitesJournalAnalysis(BaseModel):
    release_id: UUID
    exported_on: date
    indexed_through: date
    dataset_updated_on: date
    scope_publications: int = Field(ge=0)
    snapshot_publications: int = Field(ge=0)
    metrics: list[PublicationMetricAggregate] = Field(default_factory=list)
    publications: list[InCitesPublicationMetric] = Field(default_factory=list)
    scope_note: str


class JournalAnalysis(BaseModel):
    linked_publications: int = Field(ge=0)
    journal_count: int = Field(ge=0)
    top_journals: list[JournalShare]
    jcr_matched_publications: int = Field(ge=0)
    cas_matched_publications: int = Field(ge=0)
    impact_factor: ImpactFactorSummary
    jcr_quartiles: list[QuartileShare]
    cas_partitions: list[QuartileShare]
    incites: InCitesJournalAnalysis | None = None
    scope_note: str


class ProjectPublicationMetric(BaseModel):
    publication_id: str
    title: str
    publication_year: int | None = None
    journal_id: str | None = None
    journal_name: str | None = None
    impact_factor: float | None = None
    jcr_quartiles: list[str] = Field(default_factory=list)
    cas_partitions: list[str] = Field(default_factory=list)
    jcr_metric_year: int | None = None
    cas_metric_year: int | None = None


class ProjectMetricSummary(BaseModel):
    project_id: str
    project_name: str
    funding_year: int | None = None
    publication_count: int = Field(ge=0)
    publications_with_journal: int = Field(ge=0)
    jcr_matched_publications: int = Field(ge=0)
    cas_matched_publications: int = Field(ge=0)
    impact_factor: ImpactFactorSummary
    jcr_quartiles: list[QuartileShare]
    cas_partitions: list[QuartileShare]
    publications: list[ProjectPublicationMetric]


class ProjectMetricCoverage(BaseModel):
    full: int = Field(ge=0)
    partial: int = Field(ge=0)
    none: int = Field(ge=0)


class AnnualProjectMetricPortfolio(BaseModel):
    funding_year: int
    project_count: int = Field(ge=0)
    project_publication_links: int = Field(ge=0)
    unique_publications: int = Field(ge=0)
    shared_publication_links: int = Field(ge=0)
    publications_with_journal: int = Field(ge=0)
    jcr_matched_publications: int = Field(ge=0)
    cas_matched_publications: int = Field(ge=0)
    impact_factor: ImpactFactorSummary
    jcr_quartiles: list[QuartileShare]
    cas_partitions: list[QuartileShare]
    jcr_project_coverage: ProjectMetricCoverage
    cas_project_coverage: ProjectMetricCoverage
    top_journals: list[JournalShare]
    projects: list[ProjectMetricSummary]


class ProjectJournalMetricAnalysis(BaseModel):
    projects: list[ProjectMetricSummary]
    annual_portfolios: list[AnnualProjectMetricPortfolio] = Field(default_factory=list)
    year_policy: Literal["publication_year"] = "publication_year"
    scope_note: str


class OutcomeDiscipline(BaseModel):
    object_id: UUID
    name: str
    scheme: str
    code: str | None = None
    review_state: str


class OutcomeAffiliation(BaseModel):
    person_id: UUID
    person_name: str
    organization_id: UUID
    organization_name: str
    root_ids: list[UUID]
    country_code: str | None = None
    roles: list[str] = Field(default_factory=list)
    role_source: str | None = None
    relation_id: UUID
    review_state: str


class OutcomeProject(BaseModel):
    object_id: UUID
    name: str
    predicate: str
    relation_id: UUID
    review_state: str
    funding_year: int | None = None


class OutcomePaper(BaseModel):
    publication_id: UUID
    title: str
    publication_year: int | None = None
    mode: str
    author_count: int
    institution_names: list[str]
    institution_ids: list[UUID] = Field(default_factory=list)
    institution_name_by_id: dict[str, str] = Field(default_factory=dict)
    institution_count: int
    affiliation_author_count: int
    cnci: float | None = None
    times_cited: float | None = None
    impact_factor: float | None = None
    publication_type: str | None = None
    affiliations: list[OutcomeAffiliation] = Field(default_factory=list)
    disciplines: list[OutcomeDiscipline] = Field(default_factory=list)
    topics: list[OutcomeDiscipline] = Field(default_factory=list)
    projects: list[OutcomeProject] = Field(default_factory=list)


class OutcomeGroup(BaseModel):
    mode: str
    publication_count: int
    cnci_covered: int
    cnci_median: float | None = None
    cnci_mean: float | None = None
    cited_covered: int
    citations_median: float | None = None
    jcr_covered: int
    jif_median: float | None = None


class CollaborationOutcomes(BaseModel):
    definition_version: str = "collaboration-outcomes-v2"
    scope_hash: str
    metric_release_id: UUID | None = None
    metric_indexed_through: str | None = None
    groups: list[OutcomeGroup]
    papers: list[OutcomePaper]
    notes: list[str]


class ScholarGraphAnalytics(BaseModel):
    data_version: str | None = None
    scope: AppliedAnalysisScope
    coverage: AnalysisCoverage
    funding: FundingAnalysis | None = None
    people_collaboration: CollaborationNetwork | None = None
    institution_collaboration: CollaborationNetwork | None = None
    disciplines: DisciplineAnalysis | None = None
    journals: JournalAnalysis | None = None
    project_journal_metrics: ProjectJournalMetricAnalysis | None = None
    collaboration_outcomes: CollaborationOutcomes | None = None
    direction_extensions: dict[str, Any] | None = None


class AnalysisDefinition(BaseModel):
    definition_version: Literal['workbench-v3'] = 'workbench-v3'
    institution_settings: InstitutionAnalysisSettings = Field(default_factory=InstitutionAnalysisSettings)
    edge_limit: int = Field(default=120, ge=1)
    people_focus_id: UUID | None = None
    people_organization_id: UUID | None = None
    people_include_external: bool = False
    workspace_settings: dict[str, Any] = Field(default_factory=dict, max_length=30)
    start_year: int | None = Field(default=None, ge=1500, le=2200)
    end_year: int | None = Field(default=None, ge=1500, le=2200)
    project_kind_ids: list[UUID] = Field(default_factory=list, max_length=500)
    organization_ids: list[UUID] = Field(default_factory=list, max_length=500)
    scholar_ids: list[UUID] = Field(default_factory=list, max_length=500)
    custom_scope_id: UUID | None = None
    graph_query: str | None = Field(default=None, min_length=1, max_length=4000)
    minimum_publication_count: int = Field(default=2, ge=1, le=20)
    topic: Literal['collaboration-outcomes-v1'] = 'collaboration-outcomes-v1'
    comparison: dict[str, str] = Field(default_factory=dict, max_length=6)

    @field_validator("workspace_settings")
    @classmethod
    def validate_workspace_settings(cls, value: dict[str, Any]) -> dict[str, Any]:
        text_keys = {"discipline.scheme", "discipline.search", "direction.search"}
        count_keys = {"institution.minimum", "institution.clusterMinimum", "people.clusterMinimum"}
        for key, item in value.items():
            if key in text_keys:
                if not isinstance(item, str) or len(item) > 500:
                    raise ValueError(f"Invalid text preference: {key}")
            elif key in count_keys:
                if type(item) is not int or item < 1:
                    raise ValueError(f"Invalid count preference: {key}")
            elif key == "discipline.mode":
                if item not in ("distribution", "intersection"):
                    raise ValueError("Invalid discipline view")
            elif key == "direction.coverage":
                if type(item) is not bool:
                    raise ValueError("Invalid coverage preference")
            elif key == "direction.institution":
                if item is not None:
                    if not isinstance(item, dict) or set(item) != {"id", "name", "kind"}:
                        raise ValueError("Invalid institution preference")
                    if not isinstance(item["id"], str):
                        raise ValueError("Invalid institution identity")
                    UUID(item["id"])
                    if any(not isinstance(item[k], str) or len(item[k]) > 500 for k in ("name", "kind")):
                        raise ValueError("Invalid institution description")
            elif key == "institution.view":
                if not isinstance(item, dict) or set(item) - {"edgeLimit", "peopleFocusId", "peopleOrganizationId", "peopleIncludeExternal"}:
                    raise ValueError("Invalid institution exploration")
                for name, setting in item.items():
                    if name == "edgeLimit" and (type(setting) is not int or setting < 1):
                        raise ValueError("Invalid edge limit")
                    if name == "peopleIncludeExternal" and type(setting) is not bool:
                        raise ValueError("Invalid external collaborator switch")
                    if name in ("peopleFocusId", "peopleOrganizationId") and setting is not None:
                        if not isinstance(setting, str):
                            raise ValueError("Invalid exploration identity")
                        UUID(setting)
            else:
                raise ValueError(f"Unknown workspace preference: {key}")
        return value

    @model_validator(mode="after")
    def validate_year_order(self):
        if self.start_year is not None and self.end_year is not None and self.start_year > self.end_year:
            raise ValueError("Start year must not exceed end year")
        return self


class AnalysisSaveCommand(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r'\S')
    kind: Literal['template', 'snapshot']
    definition: AnalysisDefinition


class SavedAnalysis(BaseModel):
    analysis_id: UUID
    name: str
    kind: Literal['template', 'snapshot']
    definition: AnalysisDefinition
    created_at: datetime
    publication_count: int | None = None
    result_hash: str | None = None


class SavedAnalysisDetail(SavedAnalysis):
    result: ScholarGraphAnalytics | None = None
