import { PublicationJournalMetrics } from './PublicationJournalMetrics';
import { Notice as InlineNotification } from '../../shared/components/Notice';
import { useState } from 'react';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import {
  ArrowLeft, ArrowUpRight, ChartRelationship, Copy, Document, DocumentView,
  Information, Maximize, Minimize, Renew,
} from '@carbon/icons-react';
import {
  Breadcrumb, BreadcrumbItem, Button, InlineLoading, 
  Modal, SkeletonText, Tag,
} from '@carbon/react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import type {
  GraphEdge, KnowledgeObjectContributorView, KnowledgeObjectDetailView,
  KnowledgeObjectIdentifierView, KnowledgeObjectView, NeighborhoodResult,
} from '../../generated/smartlib-api';
import {
  getKnowledgeCatalogDetail,
  getKnowledgeObjectNetwork,
  getKnowledgeObjectResourceContentUrl,
} from '../../shared/api/smartlib';
import { InteractiveRelationshipGraph } from '../graph/InteractiveRelationshipGraph';
import { isClassificationNode } from './knowledgeSemantics';
import { ResearchProfilePanel } from './ResearchProfilePanel';

type OutputType = KnowledgeObjectView['object_type'];
type DetailValue = string | number | boolean | null | undefined;

const typeLabels: Partial<Record<OutputType, string>> = {
  publication: '论文', project: '项目', funding_program: '项目种类', patent: '专利', dataset: '数据集',
  person: '学者', organization: '机构', department: '院系', discipline: '学科', concept: '研究主题',
};

const predicateLabels: Record<string, string> = {
  'person.authored': '作者', 'person.leads_project': '负责项目', 'person.participates_in': '参与项目',
  'person.awardee_of': '获批人', 'project.has_representative_publication': '代表性论著',
  'project.under_program': '属于项目种类', 'publication.published_by': '发表于',
  'publication.uses_dataset': '使用数据集', 'publication.supported_by_project': '受项目资助',
  'person.affiliated_with': '论文署名关联', 'person.collaborates_with': '合作',
};

const statusLabels: Record<string, string> = {
  approved: '已核验', pending: '待核验', rejected: '已驳回', validated: '已验证',
  verified: '已核验', unverified: '待核验', review_required: '需要复核',
  published: '已发表', preprint: '预印本', early_access: '在线优先', corrected: '已更正', retracted: '已撤回',
  complete: '完整', partial: '部分补充', empty: '尚未补充', missing: '尚无全文', registered: '全文已登记',
  extracting: '正在解析', extracted: '全文已解析', failed: '解析失败', matched: '已匹配', conflict: '存在冲突',
  national: '国家级', information_pending: '信息待补',
  not_established: '尚未建立', provisional_source_and_number: '按资助来源与编号暂定识别',
};

const resourceRoleLabels = { article: '论文全文', correction: '勘误文件', supplementary: '补充材料' } as const;

const fieldLabels: Record<string, string> = {
  journal_name: '期刊', journal_abbreviation: '期刊简称', publication_year: '发表年份', year: '年度',
  published_online_at: '在线发表日期', published_print_at: '印刷发表日期', volume: '卷', issue: '期', pages: '页码',
  article_number: '文章编号', publication_type: '成果类型', language_code: '语言', publication_status: '发表状态',
  identity_state: '身份核验', enrichment_state: '信息完整度', fulltext_state: '全文状态',
  principal_investigator_name: '负责人', project_type: '项目类别', grant_number: '批准号', funding_amount: '资助金额',
  duration: '执行期限', funding_agency: '资助机构', funding_scheme: '资助体系', program_level: '计划层级',
  funding_source_category_label: '资助来源类别（暂定）', principal_investigator_status: '负责人关系',
  project_identity_status: '项目身份状态',
  project_state: '项目状态', official_guide_title: '官方指南', official_source_url: '官方来源',
  patent_number: '专利号', application_number: '申请号', filing_date: '申请日期', grant_date: '授权日期',
  patent_status: '专利状态', assignee: '权利人', country: '国家或地区',
  repository: '存储平台', accession: '数据集编号', license: '许可方式', availability: '开放状态', resource_type: '数据类型',
};

const internalKeys = new Set([
  'title', 'subtitle', 'abstract', 'metadata_version', 'last_enriched_at', 'dataset_id', 'dataset_version',
  'synthetic', 'record_kind', 'source_role', 'funding_program_id', 'principal_investigator_person_id',
  'project_title_status', 'project_type_status', 'grant_number_status', 'funding_amount_status', 'duration_status',
  'metadata_status', 'official_name_verified_on', 'review_state', 'quality_state', 'verification_state',
  'identity_state', 'enrichment_state', 'reviewed_at', 'reviewed_by',
  'source_import_batch', 'candidate_project_key', 'funding_source_category', 'source', 'category_basis',
]);

const typeFields: Partial<Record<OutputType, string[]>> = {
  publication: [
    'journal_name', 'journal_abbreviation', 'publication_year', 'published_online_at', 'published_print_at',
    'volume', 'issue', 'pages', 'article_number', 'publication_type', 'language_code', 'publication_status',
    'fulltext_state',
  ],
  project: ['principal_investigator_name', 'year', 'project_type', 'grant_number', 'funding_amount', 'duration'],
  funding_program: ['funding_source_category_label', 'funding_agency', 'funding_scheme', 'program_level', 'year', 'project_state', 'official_guide_title', 'official_source_url'],
  patent: ['patent_number', 'application_number', 'filing_date', 'grant_date', 'patent_status', 'assignee', 'country'],
  dataset: ['repository', 'accession', 'year', 'resource_type', 'license', 'availability'],
};

export function ResearchOutputDetail({ objectId }: { objectId: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const routeState = location.state as { from?: unknown } | null;
  const backTarget = typeof routeState?.from === 'string' ? routeState.from : '/outputs';
  const detail = useQuery({
    queryKey: ['knowledge-catalog-detail', objectId],
    queryFn: ({ signal }) => getKnowledgeCatalogDetail(objectId, signal),
    retry: 1,
  });
  const network = useQuery({
    queryKey: ['knowledge-object-network', objectId],
    queryFn: ({ signal }) => getKnowledgeObjectNetwork(objectId, signal),
    retry: 1,
  });

  if (detail.isPending) return <DetailLoading />;
  if (detail.isError) return <div className="sg-discovery-page sg-output-detail"><Breadcrumb noTrailingSlash><BreadcrumbItem><Link to={backTarget}>科研成果</Link></BreadcrumbItem><BreadcrumbItem isCurrentPage>加载失败</BreadcrumbItem></Breadcrumb><InlineNotification kind="error" title="成果详情暂不可用" subtitle={detail.error.message} actionButtonLabel="重试" onActionButtonClick={() => void detail.refetch()} /></div>;

  const item = detail.data.object;
  const typeLabel = typeLabels[item.object_type] ?? item.object_type;
  const classificationNode = isClassificationNode(item.object_type);
  const resolvedBackTarget = classificationNode && typeof routeState?.from !== 'string' ? '/graph-analytics' : backTarget;
  return <div className="sg-discovery-page sg-output-detail">
    <Button className="sg-detail-back" kind="ghost" size="sm" renderIcon={ArrowLeft} onClick={() => { void navigate(resolvedBackTarget); }}>{classificationNode ? '返回知识图谱' : '返回成果目录'}</Button>
    <header className="sg-output-hero">
      <div><div className="sg-output-kicker"><Tag type="cool-gray">{typeLabel}</Tag></div><h1>{displayName(item.canonical_name)}</h1>{item.object_type !== 'publication' && <p>{item.description ?? `${typeLabel}简介尚未收录。`}</p>}</div>
      <dl><div><dt>数据版本</dt><dd>{item.version}</dd></div><div><dt>更新时间</dt><dd>{displayDate(item.updated_at)}</dd></div><div><dt>系统编号</dt><dd><code>{item.object_id}</code></dd></div></dl>
    </header>
    {['publication', 'person', 'organization', 'project'].includes(item.object_type) && <p><a href="#research-profile">查看研究方向画像</a></p>}
    <main className="sg-output-layout">
      <div>
        <TypeDetails detail={detail.data} />
      </div>
      <aside>
        <IdentifierPanel detail={detail.data} />
      </aside>
    </main>
    {item.object_type === 'project' && item.attributes?.principal_investigator_status === 'not_established' && <InlineNotification kind="info" lowContrast hideCloseButton title="项目负责人尚未建立" subtitle="关联论文是本项目的资助成果。论文作者不等同项目申请人或负责人；本次只登记论文受项目资助的关系，来源类别可随权威信息修订。" />}
    {item.object_type === 'publication' && <>
      <PublicationJournalMetrics detail={detail.data} />
      <div className="sg-publication-reading-grid">
        <PublicationAbstract detail={detail.data} />
        <PublicationContributors contributors={detail.data.contributors ?? []} />
      </div>
      <PublicationResources publicationId={item.object_id} publicationTitle={item.canonical_name} resources={detail.data.resources ?? []} />
    </>}
    {['publication', 'person', 'organization', 'project'].includes(item.object_type) && <ResearchProfilePanel objectId={item.object_id} />}
    <RelationshipPanel query={network} rootName={item.canonical_name} classificationNode={classificationNode} />
    <DataTrust classificationNode={classificationNode} />
  </div>;
}

function TypeDetails({ detail }: { detail: KnowledgeObjectDetailView }) {
  const item = detail.object;
  const values = detail.type_details ?? item.attributes ?? {};
  const configured = item.object_type === 'funding_program' && item.attributes?.record_kind === 'funding_category' ? ['funding_source_category_label'] : typeFields[item.object_type] ?? [];
  const fields = configured.map((key) => ({ key, label: fieldLabels[key] ?? key, value: values[key] as DetailValue }));
  const extras = Object.entries(values).filter(([key, value]) => !configured.includes(key) && !internalKeys.has(key) && isDisplayValue(value)).map(([key, value]) => ({ key, label: fieldLabels[key] ?? humanizeKey(key), value: value as DetailValue }));
  return <>
    {item.object_type === 'project' && typeof item.attributes?.funding_program_id === 'string' && <section className="sg-output-section"><header><div><h2>所属项目种类</h2><p>资助来源类别统一维护在种类对象上，具体项目通过关系引用。</p></div></header><Link to={`/outputs/${item.attributes.funding_program_id}`}>查看项目种类及分类</Link></section>}
    <section className="sg-output-section"><header><div><h2>{typeSectionTitle(item.object_type)}</h2><p>{typeSectionDescription(item.object_type)}</p></div></header><div className="sg-output-fields">{fields.map((field) => <DetailField key={field.key} label={field.label} value={field.value} />)}</div></section>
    {extras.length > 0 && <section className="sg-output-section"><header><div><h2>补充信息</h2><p>该类型记录中已经登记的其他字段</p></div></header><div className="sg-output-fields">{extras.map((field) => <DetailField key={field.key} label={field.label} value={field.value} />)}</div></section>}
  </>;
}

function PublicationAbstract({ detail }: { detail: KnowledgeObjectDetailView }) {
  const abstract = textValue(detail.type_details?.abstract) ?? detail.object.description;
  return <section className="sg-output-section sg-publication-abstract"><header><div><h2>摘要</h2><p>来自当前已采用的论文元数据</p></div></header><p className="sg-output-abstract">{abstract ?? '摘要尚未收录。'}</p></section>;
}

function DataTrust({ classificationNode }: { classificationNode: boolean }) {
  return <section className="sg-output-section sg-output-trust"><header><div><h2>数据说明</h2><p>帮助理解这条记录当前的完整程度</p></div></header><div><Information size={20} /><p>{classificationNode ? '这是用于汇聚同类项目的种类节点，不是一项具体科研成果。资助来源粗分类统一保存在此；具体项目通过“属于项目种类”关系引用。只明确资助来源的种类仍为暂定汇聚，不表示已核准正式计划。' : '页面只显示当前身份可读取的权威业务记录和关系。缺失字段会明确标注，不使用推测内容补齐。'}</p></div></section>;
}

function DetailField({ label, value }: { label: string; value: DetailValue }) {
  const display = displayValue(value);
  const external = typeof value === 'string' && /^https?:\/\//.test(value);
  return <div><dt>{label}</dt><dd>{external ? <a href={value} target="_blank" rel="noreferrer">查看官方来源 <ArrowUpRight size={14} /></a> : display}</dd></div>;
}

function IdentifierPanel({ detail }: { detail: KnowledgeObjectDetailView }) {
  const item = detail.object;
  const identifiers = detail.identifiers ?? [];
  const configured = item.object_type === 'publication' ? ['doi', 'pmid', 'pmcid'] : item.object_type === 'project' ? ['grant_number'] : item.object_type === 'patent' ? ['patent_number', 'application_number'] : item.object_type === 'dataset' ? ['doi', 'accession'] : [];
  const rows = configured.map((kind) => identifiers.find((entry) => entry.identifier_type.toLowerCase() === kind) ?? fallbackIdentifier(item, kind));
  const additional = identifiers.filter((entry) => !configured.includes(entry.identifier_type.toLowerCase()));
  if (rows.length === 0 && additional.length === 0) return null;
  return <section className="sg-output-section sg-output-identifiers"><header><div><h2>标识符</h2><p>可复制、可跳转的标准编号</p></div></header><div>{[...rows, ...additional].map((entry) => <IdentifierRow key={`${entry.identifier_type}-${entry.value}`} entry={entry} />)}</div></section>;
}

function IdentifierRow({ entry }: { entry: KnowledgeObjectIdentifierView }) {
  const kind = entry.identifier_type.toLowerCase();
  const label = fieldLabels[kind] ?? kind.toUpperCase();
  const href = identifierHref(kind, entry.value);
  const copy = () => { if (entry.value) void navigator.clipboard.writeText(entry.value); };
  return <div><span>{label}</span>{href ? <a href={href} target="_blank" rel="noreferrer"><code>{entry.value}</code><ArrowUpRight size={14} /></a> : <code>{entry.value || '尚未收录'}</code>}<button type="button" disabled={!entry.value} aria-label={`复制 ${label}`} onClick={copy}><Copy size={14} /></button></div>;
}

function PublicationContributors({ contributors }: { contributors: KnowledgeObjectContributorView[] }) {
  return <section className="sg-output-section"><header><div><h2>作者</h2><p>按署名顺序展示；作者角色来自当前核验结果</p></div><strong>{contributors.length} 位</strong></header>{contributors.length === 0 ? <EmptyInline text="作者信息尚未进入当前记录。" /> : <ol className="sg-contributor-list">{contributors.map((author) => <li key={`${author.order}-${author.name}`}>
    <span>{author.order}</span>
    <div className="sg-contributor-entry">
      <div className="sg-contributor-heading">
        <div className="sg-contributor-name">
          <strong>{author.name}</strong>
          {author.person_object_id && <Link className="sg-contributor-scholar-link" to={`/scholars/${author.person_object_id}`} aria-label={`查看学者 ${author.name} 的详情`}><Tag type="blue">学者</Tag></Link>}
        </div>
        <div className="sg-contributor-roles">{(author.roles ?? []).map((role) => <Tag key={role} type="teal">{roleLabel(role)}</Tag>)}</div>
      </div>
      {(author.affiliations ?? []).length > 0 ? <small>{(author.affiliations ?? []).join('；')}</small> : author.affiliation && <small>{author.affiliation}</small>}
      {author.orcid && <a className="sg-contributor-orcid" href={`https://orcid.org/${author.orcid}`} target="_blank" rel="noreferrer"><code>{author.orcid}</code></a>}
    </div>
  </li>)}</ol>}</section>;
}

function PublicationResources({ publicationId, publicationTitle, resources }: { publicationId: string; publicationTitle: string; resources: KnowledgeObjectDetailView['resources'] }) {
  const rows = resources ?? [];
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>(null);
  const [isReaderExpanded, setIsReaderExpanded] = useState(false);
  const selected = rows.find((resource) => resource.resource_id === selectedResourceId);
  const contentUrl = selected ? getKnowledgeObjectResourceContentUrl(publicationId, selected.resource_id) : '';
  const closeReader = () => { setSelectedResourceId(null); setIsReaderExpanded(false); };
  return <>
    <section className="sg-output-section sg-output-resources"><header><div><h2>全文资源</h2><p>论文正文、补充材料及正式勘误文件</p></div><strong>{rows.length} 个</strong></header>{rows.length === 0 ? <EmptyInline text="当前没有可展示的全文资源。" /> : <div className="sg-resource-list">{rows.map((resource) => <article key={resource.resource_id}><Document size={22} /><div><strong>{resource.file_name}</strong><small>{resource.mime_type} · {formatBytes(resource.size_bytes)}</small></div><div className="sg-resource-tags"><Tag type={resource.resource_role === 'correction' ? 'warm-gray' : 'cool-gray'}>{resourceRoleLabels[resource.resource_role]}</Tag></div><Button kind="ghost" size="sm" renderIcon={DocumentView} onClick={() => setSelectedResourceId(resource.resource_id)}>阅读全文</Button></article>)}</div>}</section>
    <Modal className={`sg-pdf-modal${isReaderExpanded ? ' sg-pdf-modal--expanded' : ''}`} open={Boolean(selected)} passiveModal size="lg" aria-label="全文阅读窗口" closeButtonLabel="关闭" onRequestClose={closeReader}>
      {selected && <><button className="sg-pdf-window-toggle" type="button" aria-label={isReaderExpanded ? '还原阅读窗口' : '放大阅读窗口'} aria-pressed={isReaderExpanded} onClick={() => setIsReaderExpanded((value) => !value)}>{isReaderExpanded ? <Minimize size={20} /> : <Maximize size={20} />}</button><div className="sg-pdf-reader"><div><a href={contentUrl} target="_blank" rel="noreferrer">在新窗口打开 <ArrowUpRight size={14} /></a></div><iframe src={contentUrl} title={`${displayName(publicationTitle)}全文 PDF`} /></div></>}
    </Modal>
  </>;
}

function RelationshipPanel({ query, rootName, classificationNode = false }: { query: UseQueryResult<NeighborhoodResult>; rootName: string; classificationNode?: boolean }) {
  if (query.isPending) return <section className="sg-output-section sg-output-network"><InlineLoading description="正在读取成果关系图" /></section>;
  if (query.isError) return <section className="sg-output-network"><InlineNotification kind="error" title="关系图暂不可用" subtitle={`${query.error.message}。成果基本信息仍可正常查看。`} actionButtonLabel="重试" onActionButtonClick={() => void query.refetch()} /></section>;
  const network = query.data;
  if (network.edges.length === 0) return <section className="sg-output-section sg-output-network"><header><div><h2>图谱关系</h2><p>当前成果的一度关系</p></div></header><div className="sg-page-empty"><ChartRelationship size={32} /><h3>暂无可展示关系</h3><p>这表示当前查询范围内尚未建立关系，不代表该成果实际上没有作者、机构或项目关联。</p><Button kind="tertiary" renderIcon={Renew} onClick={() => void query.refetch()}>重新查询</Button></div></section>;
  return <InteractiveRelationshipGraph
    key={`${network.root_object_id}-${network.projection_version}-${network.nodes.length}-${network.edges.length}`}
    initialNetwork={network} rootName={rootName} title="图谱关系"
    description={`从当前${classificationNode ? '分类节点' : '成果'}开始逐节点探索一度关系，不一次加载全库图谱。`}
    sectionClassName="sg-output-section sg-output-network" filterId="output-network-type"
    typeLabels={typeLabels} relationLabel={relationLabel} reviewLabel={reviewLabel}
  />;
}
function relationLabel(edge: GraphEdge) { const roles = Array.isArray(edge.attributes?.roles) ? edge.attributes.roles.filter((role): role is string => typeof role === 'string' && role !== 'author') : []; return edge.predicate === 'person.authored' && roles.length ? roles.map(roleLabel).join('、') : predicateLabels[edge.predicate] ?? edge.predicate; }
function EmptyInline({ text }: { text: string }) { return <div className="sg-empty-inline"><Information size={20} /><span>{text}</span></div>; }
function DetailLoading() { return <div className="sg-discovery-page sg-detail-loading" aria-label="正在加载成果详情"><SkeletonText width="18%" /><SkeletonText heading width="55%" /><SkeletonText width="70%" /><div>{Array.from({ length: 4 }, (_, index) => <SkeletonText key={index} paragraph lineCount={4} />)}</div></div>; }
function displayName(value: string) { return value.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim(); }
function displayDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN'); }
function reviewLabel(value: string) { return statusLabels[value] ?? value; }
function textValue(value: unknown) { return typeof value === 'string' && value.trim() ? value : undefined; }
function isDisplayValue(value: unknown): value is string | number | boolean { return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'; }
function displayValue(value: DetailValue) { if (value === null || value === undefined || value === '') return '尚未收录'; if (typeof value === 'boolean') return value ? '是' : '否'; return statusLabels[String(value)] ?? String(value); }
function humanizeKey(key: string) { return key.split('_').map((part) => part ? `${part.charAt(0).toUpperCase()}${part.slice(1)}` : '').join(' '); }
function typeSectionTitle(type: OutputType) { return type === 'publication' ? '出版信息' : type === 'project' ? '项目基本信息' : type === 'funding_program' ? '资助计划信息' : type === 'patent' ? '专利信息' : type === 'dataset' ? '数据集信息' : '基本信息'; }
function typeSectionDescription(type: OutputType) { return type === 'publication' ? '期刊、出版时间与当前核验状态' : type === 'project' ? '负责人、批准号、类别与执行信息' : type === 'funding_program' ? '资助机构、年度与计划层级' : type === 'patent' ? '申请、授权与权利人信息' : type === 'dataset' ? '存储平台、编号、许可与开放状态' : '该成果当前已经登记的结构化信息'; }
function roleLabel(role: string) { return role === 'first_author' ? '第一作者' : role === 'co_first_author' ? '共同第一作者' : role === 'corresponding_author' ? '通讯作者' : role === 'co_corresponding_author' ? '共同通讯作者' : role; }
function fallbackIdentifier(item: KnowledgeObjectView, kind: string): KnowledgeObjectIdentifierView { const value = item.attributes?.[kind]; return { identifier_type: kind, value: typeof value === 'string' ? value : '', is_primary: true, verification_status: typeof value === 'string' ? 'matched' : 'pending' }; }
function identifierHref(kind: string, value: string) { if (!value) return undefined; if (kind === 'doi') return `https://doi.org/${value}`; if (kind === 'pmid') return `https://pubmed.ncbi.nlm.nih.gov/${value}/`; if (kind === 'pmcid') return `https://pmc.ncbi.nlm.nih.gov/articles/${value}/`; if (kind === 'orcid') return `https://orcid.org/${value}`; return undefined; }
function formatBytes(value?: number | null) { if (value === null || value === undefined) return '大小未知'; if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`; return `${(value / 1024 / 1024).toFixed(1)} MB`; }
