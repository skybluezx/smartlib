import { Notice as InlineNotification } from '../../shared/components/Notice';
import { useMemo } from 'react';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, ArrowUpRight, ChartRelationship, Information, Renew } from '@carbon/icons-react';
import { Breadcrumb, BreadcrumbItem, Button, InlineLoading,  SkeletonText, Tag } from '@carbon/react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import type { GraphEdge, GraphNode, InstitutionAssociationSummary, KnowledgeObjectView, NeighborhoodResult } from '../../generated/smartlib-api';
import { getKnowledgeCatalogDetail, getKnowledgeObjectNetwork } from '../../shared/api/smartlib';
import { InteractiveRelationshipGraph } from '../graph/InteractiveRelationshipGraph';
import { ResearchProfilePanel } from './ResearchProfilePanel';

type InstitutionType = Extract<KnowledgeObjectView['object_type'], 'organization' | 'department'>;

const typeLabels: Record<string, string> = {
  person: '学者', publication: '论文', organization: '机构', department: '学院与部门', discipline: '学科',
  funding_program: '资助计划', project: '项目', journal: '期刊', concept: '研究主题', dataset: '数据集', patent: '专利', resource: '资源',
};

const relationLabels: Record<string, string> = {
  'person.affiliated_with': '论文署名关联', 'person.member_of_department': '归属于', 'person.member_of_discipline': '所属学科',
  'person.researches': '研究', 'organization.has_department': '下设', 'department.part_of': '属于机构',
  'department.supports_discipline': '支撑学科', 'taxonomy.broader': '上位分类', 'taxonomy.contains': '包含',
  'publication.in_discipline': '所属学科', 'project.in_discipline': '所属学科',
};

const fieldLabels: Record<string, string> = {
  name_variants: '其他名称', organization_level: '机构层级', scheme: '分类体系', scheme_code: '分类代码', parent_code: '上位代码', level: '层级', node_type: '节点类型',
  department_code: '科学部代码', department_name: '科学部', source_authority: '来源机构', source_url: '来源链接',
  dataset_id: '数据集', dataset_version: '数据版本', source: '信息来源', official: '官方记录',
  identity_resolution_status: '机构规范化状态', extraction_status: '提取状态', scope_note: '收录范围说明',
  description_from_source: '来源说明', country: '国家或地区', city: '城市', website: '官方网站',
};

const statusLabels: Record<string, string> = {
  approved: '已核验', pending: '待核验', rejected: '已驳回', validated: '已验证', warning: '需关注',
  unverified: '待核验', normalized_name_pending_review: '名称已规范化，待复核', ocr_clean: 'OCR 识别正常',
};

const publicFields = new Set(['country', 'city', 'website', 'source_url', 'name_variants', 'organization_level']);

export function InstitutionDetail({ objectId }: { objectId: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const routeState = location.state as { from?: unknown } | null;
  const backTarget = typeof routeState?.from === 'string' ? routeState.from : '/institutions';
  const detail = useQuery({
    queryKey: ['institution-detail', objectId],
    queryFn: ({ signal }) => getKnowledgeCatalogDetail(objectId, signal),
    retry: 1,
  });
  const network = useQuery({
    queryKey: ['institution-network', objectId],
    queryFn: ({ signal }) => getKnowledgeObjectNetwork(objectId, signal),
    retry: 1,
  });

  if (detail.isPending) return <DetailLoading />;
  if (detail.isError) return <div className="sg-discovery-page sg-institution-detail"><Breadcrumb noTrailingSlash><BreadcrumbItem><Link to={backTarget}>机构字典</Link></BreadcrumbItem><BreadcrumbItem isCurrentPage>加载失败</BreadcrumbItem></Breadcrumb><InlineNotification kind="error" title="详情暂不可用" subtitle={detail.error.message} actionButtonLabel="重试" onActionButtonClick={() => void detail.refetch()} /></div>;

  const item = detail.data.object;
  if (!isInstitutionType(item.object_type)) return <div className="sg-discovery-page"><InlineNotification kind="error" title="对象类型不适用于本页面" subtitle="请返回机构字典重新选择。" /></div>;
  const values = detail.data.type_details ?? item.attributes ?? {};
  const fields = Object.entries(values).filter(([key, value]) => publicFields.has(key) && isDisplayValue(value));
  const counts = countNodeTypes(network.data);
  const associations = detail.data.institution_associations;
  return <div className="sg-discovery-page sg-institution-detail">
    <Button className="sg-detail-back" kind="ghost" size="sm" renderIcon={ArrowLeft} onClick={() => { void navigate(backTarget); }}>返回目录和原筛选位置</Button>
    <header className="sg-output-hero sg-institution-hero">
      <div><div className="sg-output-kicker"><Tag type="cool-gray">{typeLabels[item.object_type]}</Tag></div><h1>{item.canonical_name}</h1><p>机构名称与层级依据所收录的来源记录展示。</p></div>
      <dl><div><dt>更新时间</dt><dd>{displayDate(item.updated_at)}</dd></div></dl>
    </header>
    <section className="sg-institution-summary" aria-label="关系概况">
      <SummaryMetric label="关联学者" value={associations?.scholar_count ?? '—'} scope="机构及下级机构" />
      <SummaryMetric label="关联成果" value={associations?.output_count ?? '—'} scope="经关联学者去重" />
      <SummaryMetric label="机构与部门" value={network.data ? (counts.organization ?? 0) + (counts.department ?? 0) : '—'} />
      <SummaryMetric label="学科与主题" value={network.data ? (counts.discipline ?? 0) + (counts.concept ?? 0) : '—'} />
    </section>
    <main className="sg-output-layout sg-institution-layout">
      <div>
        <section className="sg-output-section"><header><div><h2>机构基本信息</h2><p>来自当前收录记录；缺失字段不会推测补齐</p></div></header>{fields.length ? <div className="sg-output-fields">{fields.map(([key, value]) => <DetailField key={key} name={key} value={value} />)}</div> : <EmptyInline text="该对象目前只有名称和简介，其他结构化字段尚未补充。" />}</section>
      </div>
      <aside>
        <section className="sg-output-section sg-output-trust"><header><div><h2>数据说明</h2><p>帮助理解当前记录的来源和边界</p></div></header><div><Information size={20} /><p>{trustText(item, values)}</p></div></section>
      </aside>
    </main>
    <ResearchProfilePanel objectId={item.object_id} title="成果研究方向" />
    <InstitutionAssociations summary={associations} />
    <RelatedObjects network={network.data} pending={network.isPending} />
    <InstitutionNetwork query={network} rootName={item.canonical_name} />
  </div>;
}

function InstitutionAssociations({ summary }: { summary?: InstitutionAssociationSummary | null | undefined }) {
  const scholars = summary?.scholars ?? [];
  const outputs = summary?.outputs ?? [];
  return <section className="sg-output-section sg-institution-associations">
    <header><div><h2>关联学者与成果</h2><p>先匹配该机构及下级机构的关联学者，再汇总这些学者的论文和项目；不据此认定人事归属</p></div></header>
    <div className="sg-institution-association-columns">
      <article><header><h3>关联学者</h3><strong>{summary?.scholar_count ?? '—'}</strong></header>{scholars.length === 0 ? <EmptyInline text={summary ? "暂无关联学者。" : "关联学者统计暂不可用。"} /> : <div className="sg-institution-association-list">{scholars.map((scholar) => <Link key={scholar.object_id} to={`/scholars/${scholar.object_id}`}><span><strong>{scholar.canonical_name}</strong><small>{scholar.output_count} 项关联成果</small></span><ArrowRight size={16} /></Link>)}</div>}</article>
      <article><header><h3>关联成果</h3><strong>{summary?.output_count ?? '—'}</strong></header>{outputs.length === 0 ? <EmptyInline text={summary ? "关联学者暂无成果。" : "关联成果统计暂不可用。"} /> : <div className="sg-institution-association-list">{outputs.map((output) => <Link key={output.object_id} to={`/outputs/${output.object_id}`}><span><strong>{output.canonical_name}</strong><small>{typeLabels[output.object_type]}{output.year ? ` · ${output.year}` : ''} · {output.scholar_count} 位关联学者</small></span><ArrowRight size={16} /></Link>)}</div>}</article>
    </div>
    {summary?.truncated && <p className="sg-institution-association-note">当前各展示前 20 条，顶部数量为完整去重统计。</p>}
  </section>;
}

function InstitutionNetwork({ query, rootName }: { query: UseQueryResult<NeighborhoodResult>; rootName: string }) {
  if (query.isPending) return <section className="sg-output-section sg-output-network"><InlineLoading description="正在读取机构关系图" /></section>;
  if (query.isError) return <section className="sg-output-network"><InlineNotification kind="error" title="关系图暂不可用" subtitle={`${query.error.message}。基本信息仍可正常查看。`} actionButtonLabel="重试" onActionButtonClick={() => void query.refetch()} /></section>;
  if (query.data.edges.length === 0) return <section className="sg-output-section sg-output-network"><header><div><h2>图谱关系</h2><p>当前对象的一度关系</p></div></header><div className="sg-page-empty"><ChartRelationship size={32} /><h3>暂无可展示关系</h3><p>当前 HugeGraph 查询范围内尚未建立关系。</p><Button kind="tertiary" renderIcon={Renew} onClick={() => void query.refetch()}>重新查询</Button></div></section>;
  const network = query.data;
  return <InteractiveRelationshipGraph
    key={`${network.root_object_id}-${network.projection_version}-${network.nodes.length}-${network.edges.length}`}
    initialNetwork={network} rootName={rootName} title="图谱关系"
    description="从当前机构开始逐节点探索一度关系，不一次加载全库图谱。"
    sectionClassName="sg-output-section sg-output-network" filterId="institution-network-type"
    typeLabels={typeLabels} relationLabel={relationLabel} reviewLabel={reviewLabel}
  />;
}

function RelatedObjects({ network, pending }: { network?: NeighborhoodResult | undefined; pending: boolean }) {
  const nodes = useMemo(() => (network?.nodes ?? []).filter((node) => node.object_id !== network?.root_object_id).slice(0, 8), [network]);
  return <section className="sg-output-section sg-related-objects sg-related-objects-wide"><header><div><h2>直接关联对象</h2><p>展示当前一度关系中的前 8 个对象，完整关系可在下方图谱继续探索</p></div><strong>{network ? Math.max(0, network.nodes.length - 1) : 0}</strong></header>{pending ? <InlineLoading description="正在读取关联对象" /> : nodes.length === 0 ? <EmptyInline text="暂无直接关联对象。" /> : <div>{nodes.map((node) => <RelatedObject key={node.object_id} node={node} />)}</div>}</section>;
}

function RelatedObject({ node }: { node: GraphNode }) {
  const target = nodeTarget(node);
  const content = <><span>{typeLabels[node.object_type] ?? node.object_type}</span><strong>{node.canonical_name}</strong>{target && <ArrowRight size={16} />}</>;
  return target ? <Link to={target}>{content}</Link> : <div>{content}</div>;
}

function DetailField({ name, value }: { name: string; value: unknown }) {
  const rendered = displayValue(value);
  const href = name === 'source_url' || name === 'website' ? (typeof value === 'string' ? value : undefined) : undefined;
  return <div><dt>{fieldLabels[name] ?? humanizeKey(name)}</dt><dd>{href ? <a href={href} target="_blank" rel="noreferrer">查看来源 <ArrowUpRight size={14} /></a> : rendered}</dd></div>;
}

function SummaryMetric({ label, value, scope = '当前一度关系' }: { label: string; value: number | string; scope?: string | undefined }) { return <div><span>{label}</span><strong>{value}</strong><small>{scope}</small></div>; }
function EmptyInline({ text }: { text: string }) { return <div className="sg-empty-inline"><Information size={20} /><span>{text}</span></div>; }
function DetailLoading() { return <div className="sg-discovery-page sg-detail-loading" aria-label="正在加载机构详情"><SkeletonText width="18%" /><SkeletonText heading width="55%" /><SkeletonText width="70%" /><div>{Array.from({ length: 4 }, (_, index) => <SkeletonText key={index} paragraph lineCount={4} />)}</div></div>; }
function relationLabel(edge: GraphEdge) { return relationLabels[edge.predicate] ?? edge.predicate; }
function reviewLabel(value: string) { return statusLabels[value] ?? value; }
function displayDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN'); }
function displayValue(value: unknown): string { if (value == null) return '尚未收录'; if (typeof value === 'boolean') return value ? '是' : '否'; if (Array.isArray(value)) return value.map(displayValue).join('、'); if (typeof value === 'object') { const record = value as Record<string, unknown>; return displayValue(record.name ?? record.value ?? record.canonical_name ?? Object.values(record).filter(v => typeof v === 'string')); } return typeof value === 'string' || typeof value === 'number' ? String(value) : '尚未收录'; }
function humanizeKey(value: string) { return value.split('_').map((part) => part ? `${part.charAt(0).toUpperCase()}${part.slice(1)}` : '').join(' '); }
function isDisplayValue(value: unknown) { return ['string', 'number', 'boolean'].includes(typeof value) || (Array.isArray(value) && value.length > 0); }
function isInstitutionType(value: KnowledgeObjectView['object_type']): value is InstitutionType { return value === 'organization' || value === 'department'; }
function countNodeTypes(network?: NeighborhoodResult) { const counts: Record<string, number> = {}; for (const node of network?.nodes ?? []) { if (node.object_id === network?.root_object_id) continue; counts[node.object_type] = (counts[node.object_type] ?? 0) + 1; } return counts; }
function nodeTarget(node: GraphNode) { if (node.object_type === 'person') return `/scholars/${node.object_id}`; if (['publication', 'project', 'patent', 'dataset', 'funding_program'].includes(node.object_type)) return `/outputs/${node.object_id}`; if (['organization', 'department'].includes(node.object_type)) return `/institutions/${node.object_id}`; return null; }
function trustText(item: KnowledgeObjectView, values: Record<string, unknown>) { if (item.object_type === 'discipline') return values.official === true ? '该分类来自已登记的正式分类体系；分类名称、代码和上下位关系按当前数据版本展示。' : '该学科记录来自当前业务数据，分类体系和来源仍需结合字段状态理解。'; return values.source === 'publication_fulltext' ? '该机构名称从论文全文作者单位署名中提取，名称已作为独立对象登记，规范机构身份仍可能需要人工复核。' : '该机构记录来自当前收录的来源；论文署名不等同于人事归属，缺失字段不作推测。'; }
