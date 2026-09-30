import { client } from '../../generated/smartlib-api/client.gen';
import {
  getGovernanceDashboard,
  getGovernanceDataAssetTrace,
  getScholarEvidence,
  getGraphAnalysisScopeOptions,
  getScholarGraphAnalytics,
  getCustomScholarGraphAnalytics,
  previewCustomGraphAnalysisScope,
  listCustomGraphAnalysisScopes,
  createCustomGraphAnalysisScope,
  deleteCustomGraphAnalysisScope,
  getScholarProfile,
  getKnowledgeHubOverview,
  getKnowledgeHubSession,
  listPublicationVerifications,
  getPublicationVerification,
  confirmPublicationVerification,
  rejectPublicationVerification,
  listPublicationFulltexts,
  listPublicationSupplements,
  submitPublicationSupplement,
  decidePublicationSupplement,
  listKnowledgeObjects,
  listKnowledgeObjectCatalog,
  getOrganizationHierarchyOptions,
  getProjectKindOptions,
  getKnowledgeObjectCatalogDetail,
  getKnowledgeNeighborhood,
  searchKnowledge,
  searchScholars,
  type KnowledgeObjectView,
  type KnowledgeObjectPage,
  type OrganizationHierarchyOptions,
  type ProjectKindOptions,
  type KnowledgeObjectDetailView,
  type NeighborhoodResult,
  type SearchResult,
  type GovernanceDashboard,
  type DataAssetTrace,
  type ScholarEvidenceBundle,
  type ScholarGraphAnalytics,
  type GraphAnalysisScopeOptions,
  type CustomGraphScopePreview,
  type SavedCustomGraphScope,
  type ScholarProfile,
  type ScholarSummary,
  type KnowledgeHubOverview,
  type KnowledgeHubSession,
  type PublicationVerificationPage,
  type PublicationVerificationDetail,
  type PublicationVerificationDecisionCommand,
  type PublicationVerificationDecisionResult,
  type PublicationSupplementCreate,
  type PublicationSupplementDecisionCommand,
  type PublicationSupplementView,
  type PublicationFulltextResourceView,
  type PublicationFulltextUploadResult,
} from '../../generated/smartlib-api';
import { runtimeConfig } from '../config/runtime';

client.setConfig({ baseUrl: runtimeConfig.apiBaseUrl });

function apiFailure(fallback: string, error: unknown): Error {
  const detail = typeof error === 'object' && error !== null && 'detail' in error
    ? String(error.detail)
    : fallback;
  return new Error(detail);
}

export async function getKnowledgeHubSessionView(): Promise<KnowledgeHubSession> {
  const { data, error } = await getKnowledgeHubSession();
  if (error) throw apiFailure('无法读取知识中台访问权限', error);
  return data;
}

export async function getKnowledgeHubOverviewView(): Promise<KnowledgeHubOverview> {
  const { data, error } = await getKnowledgeHubOverview();
  if (error) throw apiFailure('无法读取知识中台运行总览', error);
  return data;
}

export interface PublicationVerificationFilters {
  state?: string | undefined;
  fulltextStatus?: string | undefined;
  query?: string | undefined;
  page?: number | undefined;
  pageSize?: number | undefined;
}

export interface PublicationImportRecordInput {
  title: string;
  journal_name?: string | undefined;
  publication_year?: number | undefined;
  doi?: string | undefined;
  pmid?: string | undefined;
  pmcid?: string | undefined;
  authors?: string[] | undefined;
  awardee_name?: string | undefined;
  representative_work_number?: string | undefined;
}

export interface PublicationImportResult {
  batch_id: string;
  dataset_version: string;
  source_label: string;
  accepted_count: number;
  automatic_eligible_count: number;
  manual_review_count: number;
  items: {
    record_id: string;
    source_row_number: number;
    title: string;
    verification_state: string;
    automatic_verification_eligible: boolean;
    eligibility_reasons: string[];
  }[];
}

async function importResponse(response: Response): Promise<PublicationImportResult> {
  if (!response.ok) {
    const error = await response.json().catch(() => null) as { detail?: string | undefined } | null;
    throw new Error(error?.detail ?? `论文导入失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<PublicationImportResult>;
}

export async function submitSinglePublicationImport(
  sourceLabel: string,
  record: PublicationImportRecordInput,
): Promise<PublicationImportResult> {
  const baseUrl = runtimeConfig.apiBaseUrl.replace(/\/$/, '');
  return importResponse(await fetch(`${baseUrl}/api/v1/ingestion/publications`, {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_label: sourceLabel, record }),
  }));
}

export async function submitBatchPublicationImport(
  sourceLabel: string,
  file: File,
): Promise<PublicationImportResult> {
  const form = new FormData();
  form.append('source_label', sourceLabel);
  form.append('file', file);
  const baseUrl = runtimeConfig.apiBaseUrl.replace(/\/$/, '');
  return importResponse(await fetch(`${baseUrl}/api/v1/ingestion/publications/file`, {
    method: 'POST', credentials: 'same-origin', body: form,
  }));
}

export async function getPublicationVerificationPage(
  filters: PublicationVerificationFilters,
): Promise<PublicationVerificationPage> {
  const { data, error } = await listPublicationVerifications({ query: {
    state: filters.state === '' ? undefined : filters.state,
    fulltext_status: filters.fulltextStatus === '' ? undefined : filters.fulltextStatus,
    query: filters.query === '' ? undefined : filters.query,
    page: filters.page ?? 1,
    page_size: filters.pageSize ?? 20,
  } });
  if (error) throw apiFailure('无法读取论文核验队列', error);
  return data;
}

export async function getPublicationVerificationView(
  importItemId: string,
): Promise<PublicationVerificationDetail> {
  const { data, error } = await getPublicationVerification({
    path: { record_id: importItemId },
  });
  if (error) throw apiFailure('无法读取论文核验详情', error);
  return data;
}

export async function submitPublicationVerification(
  importItemId: string,
  command: PublicationVerificationDecisionCommand,
  decision: 'confirm' | 'reject',
): Promise<PublicationVerificationDecisionResult> {
  const request = decision === 'confirm' ? confirmPublicationVerification : rejectPublicationVerification;
  const { data, error } = await request({
    path: { record_id: importItemId }, body: command,
  });
  if (error) throw apiFailure('核验决定写入失败', error);
  return data;
}

export async function getPublicationSupplementsView(
  publicationId: string,
): Promise<PublicationSupplementView[]> {
  const { data, error } = await listPublicationSupplements({
    path: { publication_id: publicationId },
  });
  if (error) throw apiFailure('无法读取论文后续补充记录', error);
  return data;
}

export async function getPublicationFulltextsView(
  publicationId: string,
): Promise<PublicationFulltextResourceView[]> {
  const { data, error } = await listPublicationFulltexts({
    path: { publication_id: publicationId },
  });
  if (error) throw apiFailure('无法读取论文全文解析结果', error);
  return data;
}

export async function submitPublicationSupplementView(
  publicationId: string,
  command: PublicationSupplementCreate,
): Promise<PublicationSupplementView> {
  const { data, error } = await submitPublicationSupplement({
    path: { publication_id: publicationId }, body: command,
  });
  if (error) throw apiFailure('论文后续信息登记失败', error);
  return data;
}

export async function uploadPublicationFulltextView(
  publicationId: string,
  file: File,
  sourceLabel: string,
  resourceRole: 'article' | 'correction' | 'supplementary' = 'article',
  note?: string,
): Promise<PublicationFulltextUploadResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('source_label', sourceLabel);
  form.append('resource_role', resourceRole);
  if (note) form.append('note', note);
  const baseUrl = runtimeConfig.apiBaseUrl.replace(/\/$/, '');
  const response = await fetch(
    `${baseUrl}/api/v1/knowledge-hub/publications/${encodeURIComponent(publicationId)}/fulltext`,
    { method: 'POST', body: form, credentials: 'same-origin' },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => null) as { detail?: string | undefined } | null;
    throw new Error(error?.detail ?? `论文全文上传失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<PublicationFulltextUploadResult>;
}

export async function decidePublicationSupplementView(
  supplementId: string,
  command: PublicationSupplementDecisionCommand,
): Promise<PublicationSupplementView> {
  const { data, error } = await decidePublicationSupplement({
    path: { submission_id: supplementId }, body: command,
  });
  if (error) throw apiFailure('论文变更审核失败', error);
  return data;
}

export async function getGovernanceDashboardView(): Promise<GovernanceDashboard> {
  const { data, error } = await getGovernanceDashboard();
  if (error) throw new Error('治理服务返回错误');
  return data;
}

export async function getGovernanceAssetTrace(dataAssetId: string): Promise<DataAssetTrace> {
  const { data, error } = await getGovernanceDataAssetTrace({
    path: { data_asset_id: dataAssetId },
  });
  if (error) throw new Error('治理追溯服务返回错误');
  return data;
}

export async function getVisibleKnowledgeObjects(limit = 8): Promise<KnowledgeObjectView[]> {
  const { data, error } = await listKnowledgeObjects({ query: { limit } });
  if (error) throw new Error('平台 API 返回错误');
  return data;
}

export interface KnowledgeCatalogQuery {
  objectTypes: KnowledgeObjectView['object_type'][];
  linkedOnly?: boolean | undefined;
  query?: string | undefined;
  page?: number | undefined;
  pageSize?: number | undefined;
  sort?: 'updated' | 'name' | 'year' | undefined;
  hierarchyRootId?: string | undefined;
  organizationLevel?: number | undefined;
  projectKindId?: string | undefined;
}

export async function getKnowledgeCatalog(
  filters: KnowledgeCatalogQuery,
  signal?: AbortSignal,
): Promise<KnowledgeObjectPage> {
  const { data, error } = await listKnowledgeObjectCatalog({
    query: {
      object_types: filters.objectTypes,
      linked_only: filters.linkedOnly,
      query: filters.query === '' ? undefined : filters.query,
      page: filters.page ?? 1,
      page_size: filters.pageSize ?? 20,
      sort: filters.sort ?? 'updated',
      hierarchy_root_id: filters.hierarchyRootId,
      organization_level: filters.organizationLevel,
      project_kind_id: filters.projectKindId,
    },
    ...(signal ? { signal } : {}),
  });
  if (error) throw apiFailure('目录服务暂不可用', error);
  return data;
}

export async function getOrganizationHierarchyFilterOptions(
  signal?: AbortSignal,
): Promise<OrganizationHierarchyOptions> {
  const { data, error } = await getOrganizationHierarchyOptions({ ...(signal ? { signal } : {}) });
  if (error) throw apiFailure('机构层级筛选暂不可用', error);
  return data;
}

export async function getProjectKindFilterOptions(
  signal?: AbortSignal,
): Promise<ProjectKindOptions> {
  const { data, error } = await getProjectKindOptions({ ...(signal ? { signal } : {}) });
  if (error) throw apiFailure('项目种类筛选暂不可用', error);
  return data;
}

export async function getKnowledgeCatalogDetail(
  objectId: string,
  signal?: AbortSignal,
): Promise<KnowledgeObjectDetailView> {
  const { data, error } = await getKnowledgeObjectCatalogDetail({
    path: { object_id: objectId }, ...(signal ? { signal } : {}),
  });
  if (error) throw apiFailure('对象详情暂不可用', error);
  return data;
}

export function getKnowledgeObjectResourceContentUrl(objectId: string, resourceId: string): string {
  const baseUrl = runtimeConfig.apiBaseUrl.replace(/\/$/, '');
  return `${baseUrl}/api/v1/catalog/objects/${encodeURIComponent(objectId)}/resources/${encodeURIComponent(resourceId)}/content`;
}

export async function getKnowledgeObjectNetwork(
  objectId: string,
  signal?: AbortSignal,
): Promise<NeighborhoodResult> {
  return getKnowledgeNeighborhoodView(objectId, signal);
}

export async function getKnowledgeNeighborhoodView(
  rootObjectId: string,
  signal?: AbortSignal,
): Promise<NeighborhoodResult> {
  const response = await fetch(`${runtimeConfig.apiBaseUrl.replace(/\/$/, '')}/api/v1/catalog/objects/${encodeURIComponent(rootObjectId)}/complete-neighborhood`, { ...(signal ? { signal } : {}), credentials: 'same-origin' });
  if (!response.ok) throw new Error('完整关系暂时无法读取，请重试');
  return response.json() as Promise<NeighborhoodResult>;
}

export async function searchVisibleKnowledge(queryText: string, signal?: AbortSignal): Promise<SearchResult> {
  const { data, error } = await searchKnowledge({
    body: {
      query_text: queryText,
      retrieval_mode: 'lexical',
      page_size: 8,
    }, ...(signal ? { signal } : {}),
  });
  if (error) throw new Error('检索服务返回错误');
  return data;
}

export interface VisibleKnowledgeNetwork {
  rootName: string;
  result: NeighborhoodResult;
}

export async function getVisibleKnowledgeNetwork(
  rootQuery = 'SmartLib 学校知识基础设施',
): Promise<VisibleKnowledgeNetwork> {
  const search = await searchVisibleKnowledge(rootQuery);
  const root = search.hits[0];
  if (!root) throw new Error('尚未找到可见的知识网络起点');
  const { data, error } = await getKnowledgeNeighborhood({
    body: {
      root_object_id: root.object_id,
      direction: 'both',
      max_depth: 2,
      limit: 20,
    },
  });
  if (error) throw new Error('知识网络服务返回错误');
  return { rootName: root.canonical_name, result: data };
}

export interface ScholarDirectoryQuery {
  query?: string | undefined;
  department?: string | undefined;
  researchDirection?: string | undefined;
  limit?: number | undefined;
}

export async function searchScholarDirectory(
  filters: ScholarDirectoryQuery = {},
  signal?: AbortSignal,
): Promise<ScholarSummary[]> {
  const { data, error } = await searchScholars({
    query: {
      query: filters.query ?? undefined,
      department: filters.department ?? undefined,
      research_direction: filters.researchDirection ?? undefined,
      limit: filters.limit ?? 50,
    }, ...(signal ? { signal } : {}),
  });
  if (error) throw new Error('学者目录服务返回错误');
  return data;
}

export async function getScholarProfileView(scholarId: string, signal?: AbortSignal): Promise<ScholarProfile> {
  const { data, error } = await getScholarProfile({ path: { scholar_id: scholarId }, ...(signal ? { signal } : {}) });
  if (error) throw new Error('学者画像服务返回错误');
  return data;
}

export async function getScholarNetworkView(scholarId: string, signal?: AbortSignal): Promise<NeighborhoodResult> {
  const profile = await getScholarProfileView(scholarId, signal);
  return getKnowledgeNeighborhoodView(profile.summary.object_id, signal);
}

export async function getScholarEvidenceView(scholarId: string, signal?: AbortSignal): Promise<ScholarEvidenceBundle> {
  const { data, error } = await getScholarEvidence({ path: { scholar_id: scholarId }, ...(signal ? { signal } : {}) });
  if (error) throw new Error('学者证据服务返回错误');
  return data;
}

export async function getScholarGraphAnalyticsView(
  query: GraphAnalysisQuery = {},
  signal?: AbortSignal,
): Promise<ScholarGraphAnalytics> {
  const common = {
    ...(query.selectedModule ? {selected_module: query.selectedModule} : {}),
    ...(query.institutionSettings ? {institution_settings: query.institutionSettings} : {}),
    minimum_publication_count: query.minimumPublicationCount ?? 2,
    edge_limit: query.edgeLimit ?? 120,
    people_include_external: query.peopleIncludeExternal ?? false,
    ...(query.peopleFocusId ? { people_focus_id: query.peopleFocusId } : {}),
    ...(query.peopleOrganizationId ? { people_organization_id: query.peopleOrganizationId } : {}),
    ...(query.startYear !== undefined ? { start_year: query.startYear } : {}),
    ...(query.endYear !== undefined ? { end_year: query.endYear } : {}),
    ...(query.projectKindIds !== undefined ? { project_kind_ids: query.projectKindIds } : {}),
    ...(query.organizationIds !== undefined ? { organization_ids: query.organizationIds } : {}),
    ...(query.scholarIds !== undefined ? { scholar_ids: query.scholarIds } : {}),
  };
  const response = query.customGraphQuery
    ? await getCustomScholarGraphAnalytics({ body: { ...common, graph_query: query.customGraphQuery }, ...(signal ? { signal } : {}) })
    : await getScholarGraphAnalytics({ query: { ...common, ...(query.customScopeId ? { custom_scope_id: query.customScopeId } : {}) }, ...(signal ? { signal } : {}) });
  const { data, error } = response;
  if (error) throw apiFailure('图谱分析服务暂不可用', error);
  return data;
}

export interface GraphAnalysisQuery {
  selectedModule?: 'journals' | 'funding' | 'project_journal_metrics' | 'disciplines' | 'people_collaboration' | 'institution_collaboration' | 'collaboration_outcomes';
  institutionSettings?: string | undefined;
  minimumPublicationCount?: number | undefined;
  edgeLimit?: number | undefined;
  peopleFocusId?: string | undefined;
  peopleOrganizationId?: string | undefined;
  peopleIncludeExternal?: boolean | undefined;
  startYear?: number | undefined;
  endYear?: number | undefined;
  projectKindIds?: string[] | undefined;
  organizationIds?: string[] | undefined;
  scholarIds?: string[] | undefined;
  customScopeId?: string | undefined;
  customGraphQuery?: string | undefined;
}

export async function getGraphAnalysisScopeOptionsView(
  signal?: AbortSignal,
): Promise<GraphAnalysisScopeOptions> {
  const { data, error } = await getGraphAnalysisScopeOptions({ ...(signal ? { signal } : {}) });
  if (error) throw apiFailure('分析范围选项暂不可用', error);
  return data;
}

export async function previewCustomGraphScopeView(
  graphQuery: string,
): Promise<CustomGraphScopePreview> {
  const { data, error } = await previewCustomGraphAnalysisScope({ body: { graph_query: graphQuery } });
  if (error) throw apiFailure('自定义图查询执行失败', error);
  return data;
}

export async function listCustomGraphScopesView(): Promise<SavedCustomGraphScope[]> {
  const { data, error } = await listCustomGraphAnalysisScopes();
  if (error) throw apiFailure('无法读取已保存的自定义范围', error);
  return data;
}

export async function saveCustomGraphScopeView(
  name: string,
  description: string,
  graphQuery: string,
): Promise<SavedCustomGraphScope> {
  const { data, error } = await createCustomGraphAnalysisScope({
    body: { name, description: description || undefined, graph_query: graphQuery },
  });
  if (error) throw apiFailure('自定义范围保存失败', error);
  return data;
}

export async function deleteCustomGraphScopeView(scopeId: string): Promise<void> {
  const { error } = await deleteCustomGraphAnalysisScope({ path: { scope_id: scopeId } });
  if (error) throw apiFailure('自定义范围删除失败', error);
}
