import { requiredValue } from '../../shared/requiredValue';
import { Notice as InlineNotification } from '../../shared/components/Notice';
import { useDeferredValue } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, ArrowUpRight, Document, Education, Information } from '@carbon/icons-react';
import { ComboBox, Dropdown, InlineLoading,  Pagination, Search, Tag } from '@carbon/react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import type { KnowledgeObjectView } from '../../generated/smartlib-api';
import {
  getKnowledgeCatalog,
  getOrganizationHierarchyFilterOptions,
  getProjectKindFilterOptions,
} from '../../shared/api/smartlib';

type ObjectType = KnowledgeObjectView['object_type'];

interface CatalogType {
  id: ObjectType;
  label: string;
}

interface KnowledgeCatalogProps {
  title: string;
  description: string;
  searchPlaceholder: string;
  types: CatalogType[];
  kind: 'outputs' | 'institutions';
  showTypeFilter?: boolean | undefined;
}

const sortItems = [
  { id: 'updated', label: '最近更新' },
  { id: 'name', label: '名称顺序' },
  { id: 'year', label: '年份从新到旧' },
] as const;

function textAttribute(item: KnowledgeObjectView, key: string) {
  const value = item.attributes?.[key];
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function yearAttribute(item: KnowledgeObjectView) {
  const value = item.object_type === 'publication' ? item.publication_year : item.attributes?.year;
  return typeof value === 'number' || typeof value === 'string' ? String(value) : undefined;
}

function projectMetadata(item: KnowledgeObjectView) {
  if (item.object_type === 'funding_program') return ['年度资助计划'];
  if (item.object_type !== 'project') return [];
  const principalInvestigator = textAttribute(item, 'principal_investigator_name');
  const projectType = textAttribute(item, 'project_type');
  const grantNumber = textAttribute(item, 'grant_number');
  return [
    principalInvestigator ? `负责人 ${principalInvestigator}` : undefined,
    projectType ? `类别 ${projectType}` : '类别待补',
    grantNumber ? `批准号 ${grantNumber}` : '批准号待补',
  ].filter((value): value is string => Boolean(value));
}

function organizationLevel(item: KnowledgeObjectView) {
  const value = item.attributes?.organization_level;
  return typeof value === 'number' || typeof value === 'string' ? String(value) : undefined;
}

function displayDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN');
}

function displayName(value: string) {
  return value.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
}

function levelLabel(level: number) {
  return ({ 1: '一', 2: '二', 3: '三', 4: '四', 5: '五' } as Record<number, string>)[level] ?? String(level);
}

export function KnowledgeCatalog({ title, description, searchPlaceholder, types, kind, showTypeFilter = true }: KnowledgeCatalogProps) {
  const [params, setParams] = useSearchParams();
  const query = params.get('q') ?? '';
  const deferredQuery = useDeferredValue(query.trim());
  const selectedType = showTypeFilter ? params.get('type') ?? 'all' : 'all';
  const projectFilterEnabled = kind === 'outputs' && selectedType === 'project';
  const projectKindId = projectFilterEnabled ? params.get('projectKind') ?? undefined : undefined;
  const hierarchyFiltersEnabled = kind === 'institutions';
  const hierarchyRootId = hierarchyFiltersEnabled ? params.get('root') ?? undefined : undefined;
  const levelValue = hierarchyFiltersEnabled ? Number(params.get('level')) : Number.NaN;
  const organizationLevel = Number.isInteger(levelValue) && levelValue > 0 ? levelValue : undefined;
  const sort = (params.get('sort') ?? (kind === 'outputs' ? 'year' : 'name')) as 'updated' | 'name' | 'year';
  const page = Math.max(1, Number(params.get('page') ?? '1') || 1);
  const pageSizeValue = Number(params.get('pageSize') ?? '20');
  const pageSize = [10, 20, 50].includes(pageSizeValue) ? pageSizeValue : 20;
  const allowedTypes = types.map((item) => item.id);
  const hierarchyFilterActive = Boolean(hierarchyRootId ?? organizationLevel);
  const requestedTypes = allowedTypes.includes(selectedType as ObjectType)
    ? [selectedType as ObjectType]
    : hierarchyFilterActive
      ? allowedTypes.filter((type) => type === 'organization' || type === 'department')
      : allowedTypes;
  const hierarchyOptions = useQuery({
    queryKey: ['organization-hierarchy-options'],
    queryFn: ({ signal }) => getOrganizationHierarchyFilterOptions(signal),
    enabled: kind === 'institutions',
    staleTime: 5 * 60 * 1000,
  });
  const projectKindOptions = useQuery({
    queryKey: ['project-kind-options'],
    queryFn: ({ signal }) => getProjectKindFilterOptions(signal),
    enabled: projectFilterEnabled,
    staleTime: 5 * 60 * 1000,
  });
  const result = useQuery({
    queryKey: ['knowledge-catalog', kind, requestedTypes, deferredQuery, kind === 'institutions' ? null : page, kind === 'institutions' ? null : pageSize, sort, hierarchyRootId, organizationLevel, projectKindId],
    queryFn: async ({ signal }) => {
      const filters = {
      objectTypes: requestedTypes,
      linkedOnly: kind === 'institutions',
      query: deferredQuery,
      page: kind === 'institutions' ? 1 : page,
      pageSize: kind === 'institutions' ? 100 : pageSize,
      sort,
      hierarchyRootId,
      organizationLevel,
      projectKindId,
      };
      const first = await getKnowledgeCatalog(filters, signal);
      if (kind !== 'institutions') return first;
      // Group across API pages so pagination never detaches children.
      const items = [...first.items];
      for (let next = 2; (next - 1) * first.page_size < first.total; next += 1) {
        const batch = await getKnowledgeCatalog({ ...filters, page: next }, signal);
        items.push(...batch.items);
      }
      return { ...first, items };
    },
    placeholderData: (previous) => previous,
  });

  const update = (changes: Record<string, string | number | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      const isDefault = value === null || value === '' || value === 'all' || (key === 'page' && value === 1) || (key === 'pageSize' && value === 20);
      if (isDefault) next.delete(key); else next.set(key, String(value));
    }
    setParams(next, { replace: true });
  };
  const typeItems = [{ id: 'all', label: '全部类型' }, ...types];
  const scopeItems = [
    { id: 'all', label: '全部机构' },
    ...(hierarchyOptions.data?.scopes ?? []).map((scope) => ({
      id: scope.object_id,
      label: displayName(scope.canonical_name),
    })),
  ];
  const levelItems = [
    { id: 'all', label: '全部层级' },
    ...(hierarchyOptions.data?.levels ?? []).map((level) => ({ id: String(level), label: `仅${levelLabel(level)}级机构` })),
  ];
  const projectKindItems = [
    { id: 'all', label: '全部项目种类' },
    ...(projectKindOptions.data?.items ?? []).map((item) => ({
      id: item.object_id,
      label: `${displayName(item.canonical_name)}（${item.project_count}）`,
    })),
  ];
  const selectedSort = sortItems.find((item) => item.id === sort) ?? sortItems[0];
  const emptyTitle = deferredQuery ? `没有找到包含“${deferredQuery}”的记录` : `当前暂无可展示的${title}`;

  return <div className="sg-discovery-page sg-catalog-page">
    <header className="sg-page-heading"><div><h1>{title}</h1><span>{description}</span></div></header>
    <section className={`sg-catalog-toolbar${kind === 'institutions' ? ' sg-catalog-toolbar--institutions' : ''}${projectFilterEnabled ? ' sg-catalog-toolbar--project' : ''}`} aria-label={`${title}筛选`}>
      <Search size="lg" labelText={`搜索${title}`} placeholder={searchPlaceholder} value={query} onChange={(event) => update({ q: event.target.value, page: 1 })} />
      {showTypeFilter && <Dropdown id={`${kind}-type`} label="类型" titleText="类型" items={typeItems} itemToString={(item) => item?.label ?? ''} selectedItem={typeItems.find((item) => item.id === selectedType) ?? typeItems[0]} onChange={({ selectedItem }) => update({ type: selectedItem?.id ?? 'all', projectKind: null, root: hierarchyRootId ?? null, level: organizationLevel ?? null, page: 1 })} />}
      {projectFilterEnabled && <ComboBox id="project-kind" titleText="项目种类" placeholder="选择或搜索项目种类" items={projectKindItems} itemToString={(item) => item?.label ?? ''} selectedItem={projectKindItems.find((item) => item.id === projectKindId) ?? projectKindItems[0]} disabled={projectKindOptions.isPending || projectKindOptions.isError} onChange={({ selectedItem }) => update({ projectKind: selectedItem?.id ?? 'all', page: 1 })} />}
      {kind === 'institutions' && <Dropdown id="institution-scope" label="查看范围" titleText="查看范围" items={scopeItems} itemToString={(item) => item?.label ?? ''} selectedItem={scopeItems.find((item) => item.id === hierarchyRootId) ?? scopeItems[0]} disabled={!hierarchyFiltersEnabled || hierarchyOptions.isPending || hierarchyOptions.isError} onChange={({ selectedItem }) => update({ root: selectedItem?.id ?? 'all', page: 1 })} />}
      {kind === 'institutions' && <Dropdown id="institution-level" label="查看粒度" titleText="查看粒度" items={levelItems} itemToString={(item) => item?.label ?? ''} selectedItem={levelItems.find((item) => item.id === String(organizationLevel)) ?? levelItems[0]} disabled={!hierarchyFiltersEnabled || hierarchyOptions.isPending || hierarchyOptions.isError} onChange={({ selectedItem }) => update({ level: selectedItem?.id ?? 'all', page: 1 })} />}
      <Dropdown id={`${kind}-sort`} label="排序" titleText="排序" items={[...sortItems]} itemToString={(item) => item?.label ?? ''} selectedItem={selectedSort} onChange={({ selectedItem }) => selectedItem && update({ sort: selectedItem.id, page: 1 })} />
    </section>
    {kind === 'institutions' && hierarchyOptions.isError && <section className="sg-state-section"><InlineNotification lowContrast kind="warning" title="机构层级筛选暂不可用" subtitle="仍可按关键词、类型和排序浏览目录。" actionButtonLabel="重试" onActionButtonClick={() => void hierarchyOptions.refetch()} /></section>}
    {projectFilterEnabled && projectKindOptions.isError && <section className="sg-state-section"><InlineNotification lowContrast kind="warning" title="项目种类筛选暂不可用" subtitle="仍可浏览全部项目，并继续使用关键词和排序。" actionButtonLabel="重试" onActionButtonClick={() => void projectKindOptions.refetch()} /></section>}
    {result.isFetching && !result.data && <section className="sg-state-section"><InlineLoading description={`正在读取${title}`} /></section>}
    {result.isError && <section className="sg-state-section"><InlineNotification kind="error" title={`${title}暂不可用`} subtitle={`${result.error.message}。学者目录和首页检索仍可使用。`} actionButtonLabel="重试" onActionButtonClick={() => void result.refetch()} /></section>}
    {result.data && <section className="sg-catalog-results" aria-live="polite">
      <div className="sg-results-summary"><strong>{result.data.total}</strong><span>条记录</span><small>{result.isFetching ? '正在更新结果' : kind === 'institutions' ? '按上级机构分组，默认折叠' : `第 ${result.data.page} 页`}</small></div>
      {result.data.items.length === 0 && <div className="sg-page-empty">{kind === 'outputs' ? <Document size={32} /> : <Education size={32} />}<h2>{emptyTitle}</h2><p>{deferredQuery ? '请缩短关键词或切换类型。' : kind === 'institutions' ? '当前没有与本校学者、成果、项目等业务对象建立关系的机构记录；未关联的机构元数据不会在此展示。' : '权威业务库中尚未建立该类对象，页面不会使用演示数据填充。'}</p></div>}
      {kind === 'institutions' ? <InstitutionTree key={`${deferredQuery}:${hierarchyRootId}:${organizationLevel}:${sort}:${page}:${pageSize}`} items={result.data.items} page={page} pageSize={pageSize} onPageChange={(nextPage, nextSize) => update({ page: nextPage, pageSize: nextSize })} /> : <div className="sg-catalog-list">{result.data.items.map((item) => <CatalogRow key={item.object_id} item={item} typeLabel={types.find((type) => type.id === item.object_type)?.label ?? item.object_type} kind={kind} />)}</div>}
      {kind !== 'institutions' && result.data.total > pageSize && <Pagination page={result.data.page} pageSize={result.data.page_size} pageSizes={[10, 20, 50]} totalItems={result.data.total} itemsPerPageText="每页" itemRangeText={(min, max, total) => `${min}–${max} / ${total}`} pageRangeText={(_, total) => `共 ${total} 页`} onChange={({ page: nextPage, pageSize: nextSize }) => update({ page: nextPage, pageSize: nextSize })} />}
    </section>}
  </div>;
}

function InstitutionTree({ items, page, pageSize, onPageChange }: { items: KnowledgeObjectView[]; page: number; pageSize: number; onPageChange: (page: number, size: number) => void }) {
  const location = useLocation();
  const byId = new Map(items.map((item) => [item.object_id, item]));
  const groups = new Map<string, { id: string; name: string; item?: KnowledgeObjectView | undefined; children: KnowledgeObjectView[] }>();
  for (const item of byId.values()) {
    // Multiple ancestors may describe a deeper chain or multiple parents. Keep
    // these records standalone with their path rather than invent a level.
    const parent = item.hierarchy_path?.length === 1 && item.hierarchy_path[0]?.object_id !== item.object_id ? item.hierarchy_path[0] : undefined;
    const rootId = parent?.object_id ?? item.object_id;
    if (!groups.has(rootId)) groups.set(rootId, { id: rootId, name: parent?.canonical_name ?? item.canonical_name, item: byId.get(rootId), children: [] });
    if (rootId !== item.object_id) requiredValue(groups.get(rootId)).children.push(item);
  }
  const rows = [...groups.values()];
  const currentPage = Math.min(page, Math.max(1, Math.ceil(rows.length / pageSize)));
  return <>
    <div className="sg-catalog-list sg-institution-tree">
      {rows.slice((currentPage - 1) * pageSize, currentPage * pageSize).map((group) => <section className="sg-institution-tree-group" key={group.id}>
        {group.item ? <CatalogRow item={group.item} typeLabel="机构" kind="institutions" /> : <div className="sg-institution-tree-context"><h2><Link to={`/institutions/${group.id}`} state={{ from: `${location.pathname}${location.search}` }}>{displayName(group.name)}<ArrowRight size={17} /></Link></h2><small>上级机构 · 下方为符合筛选条件的机构</small></div>}
        {group.children.length > 0 && <details className="sg-institution-tree-branch"><summary>{group.children.length} 个下级机构</summary><ul>{group.children.map((child) => <li key={child.object_id}><CatalogRow item={child} typeLabel="机构" kind="institutions" nested /></li>)}</ul></details>}
      </section>)}
    </div>
    {rows.length > pageSize && <Pagination page={currentPage} pageSize={pageSize} pageSizes={[10, 20, 50]} totalItems={rows.length} itemsPerPageText="每页机构组" itemRangeText={(min, max, total) => `${min}–${max} / ${total} 组`} pageRangeText={(_, total) => `共 ${total} 页`} onChange={({ page: next, pageSize: size }) => onPageChange(next, size)} />}
  </>;
}

function CatalogRow({ item, typeLabel, kind, nested = false }: { item: KnowledgeObjectView; typeLabel: string; kind: 'outputs' | 'institutions'; nested?: boolean | undefined }) {
  const location = useLocation();
  const doi = textAttribute(item, 'doi');
  const pmid = textAttribute(item, 'pmid');
  const pmcid = textAttribute(item, 'pmcid');
  const year = yearAttribute(item);
  const projectMeta = projectMetadata(item);
  const isOrganization = kind === 'institutions' && (item.object_type === 'organization' || item.object_type === 'department');
  const hierarchy = item.hierarchy_path ?? [];
  const level = organizationLevel(item);
  const numericLevel = level && /^\d+$/.test(level) ? Number(level) : undefined;
  const showHierarchy = !nested && isOrganization && (hierarchy.length > 0 || (numericLevel !== undefined && numericLevel >= 2));
  return <article className={`sg-catalog-row${kind === 'institutions' ? ' sg-catalog-row--institutions' : ''}`}>
    {kind !== 'institutions' && <div className="sg-catalog-type"><Tag type="cool-gray">{typeLabel}</Tag></div>}
    <div className="sg-catalog-main"><h2><Link to={`/${kind === 'outputs' ? 'outputs' : 'institutions'}/${item.object_id}`} state={{ from: `${location.pathname}${location.search}` }}>{displayName(item.canonical_name)}<ArrowRight size={17} /></Link></h2>{kind === 'institutions' && <div className="sg-catalog-level">{isOrganization && <Tag type="cool-gray" size="sm">{numericLevel ? `${levelLabel(numericLevel)}级` : '层级待补'}</Tag>}</div>}{showHierarchy && <div className="sg-catalog-hierarchy"><span>机构层次</span>{hierarchy.length > 0 ? <>{hierarchy.map((node) => <Link key={node.object_id} to={`/institutions/${node.object_id}`} state={{ from: `${location.pathname}${location.search}` }}>{displayName(node.canonical_name)}</Link>)}<strong>{displayName(item.canonical_name)}</strong></> : <><em>上级机构待补</em><strong>{displayName(item.canonical_name)}</strong></>}</div>}<p>{item.description ?? (kind === 'outputs' ? '当前记录尚未提供成果摘要。' : '当前记录尚未提供机构简介。')}</p><div className="sg-catalog-meta">{year && <span>年份 <strong>{year}</strong></span>}{projectMeta.map((value) => <span key={value}>{value}</span>)}{doi && <a href={`https://doi.org/${doi}`} target="_blank" rel="noreferrer">DOI <code>{doi}</code><ArrowUpRight /></a>}{pmid && <a href={`https://pubmed.ncbi.nlm.nih.gov/${pmid}/`} target="_blank" rel="noreferrer">PMID <code>{pmid}</code><ArrowUpRight /></a>}{pmcid && <a href={`https://pmc.ncbi.nlm.nih.gov/articles/${pmcid}/`} target="_blank" rel="noreferrer">PMCID <code>{pmcid}</code><ArrowUpRight /></a>}{!year && !doi && !pmid && !pmcid && projectMeta.length === 0 && <span><Information />详细字段尚未收录</span>}</div></div>
    <div className="sg-catalog-update"><span>更新于</span><strong>{displayDate(item.updated_at)}</strong><code>{item.object_id.slice(0, 8)}</code></div>
  </article>;
}
