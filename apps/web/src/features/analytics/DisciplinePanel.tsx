import { useSessionState } from './useSessionState';
import { useWorkbenchPreference } from './workbenchSettings';
import { DirectionExtensions } from './DirectionExtensions';
import { useMemo, useState, type CSSProperties } from 'react';
import { Analytics, Information } from '@carbon/icons-react';
import {
  Button, Dropdown, InlineNotification, Modal, Pagination, Search,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@carbon/react';
import { Link } from 'react-router-dom';
import type { DisciplineWorkspace } from '../../generated/smartlib-api';

const percent = (count: number, total: number) => total ? `${(count / total * 100).toFixed(1)}%` : '—';
const roleLabel = (role: string, scheme: string) => scheme === 'INCITES_WOS' ? '外部标引'
  : ({ primary: '主分类', secondary: '辅助分类' }[role] ?? '角色未标注');
const sourceLabel = (source: string) => ({ algorithmic_inference: '系统内容分类', external_indexing: '外部数据库标引' }[source] ?? '来源类型未标注');
interface Selection { title: string; concepts: string[] }

export function DisciplinePanel({ workspace, dataVersion }: { workspace: DisciplineWorkspace | null | undefined; dataVersion?: string | null | undefined }) {
  if (!workspace) return <InlineNotification kind="warning" title="学科分析数据暂不可用" subtitle="当前接口未返回新版分类明细，请刷新分析后重试。其他分析模块仍可使用。" hideCloseButton />;
  return <DisciplineWorkbench workspace={workspace} dataVersion={dataVersion} />;
}

function DisciplineWorkbench({ workspace, dataVersion }: { workspace: DisciplineWorkspace; dataVersion?: string | null | undefined }) {
  // GB/T remains available in the data layer, but is not a discovery entry point.
  const schemes = useMemo(() => workspace.schemes.filter((item) => !/^GBT_13745(?:_|$)/.test(item.scheme)), [workspace.schemes]);
  const [schemeKey, setSchemeKey] = useWorkbenchPreference('discipline.scheme', schemes[0]?.key ?? '');
  const [query, setQuery] = useWorkbenchPreference('discipline.search', '');
  const [mode, setMode] = useWorkbenchPreference('discipline.mode', 'distribution');
  const [page, setPage] = useSessionState('discipline.page',1);
  const [size, setSize] = useSessionState('discipline.pageSize',20);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [detailPage, setDetailPage] = useState(1);
  const scheme = schemes.find((item) => item.key === schemeKey) ?? schemes[0];
  const lookup = useMemo(() => new Map(scheme?.directions.map((item) => [item.object_id, item]) ?? []), [scheme]);
  const search = query.trim().toLocaleLowerCase();
  const matches = (id: string) => {
    const item = lookup.get(id);
    return `${item?.name ?? ''} ${item?.code ?? ''}`.toLocaleLowerCase().includes(search);
  };
  const directions = scheme?.directions.filter((item) => matches(item.object_id)) ?? [];
  const intersections = scheme?.intersections.filter((item) => matches(item.left_id) || matches(item.right_id)) ?? [];
  const total = mode === 'distribution' ? directions.length : intersections.length;
  const displayPage = Math.min(page, Math.max(1, Math.ceil(total / size)));
  const start = (displayPage - 1) * size;
  const paperMap = useMemo(() => new Map(workspace.papers.map((paper) => [paper.object_id, paper])), [workspace.papers]);
  // Re-resolve evidence against refreshed relations without discarding the user's filters.
  const selectedIds = selection?.concepts.length ? (lookup.get(selection.concepts[0] ?? '')?.publication_ids ?? [])
    .filter((id) => selection.concepts.every((concept) => lookup.get(concept)?.publication_ids.includes(id))) : [];
  const selectedPapers = selectedIds.map((id) => paperMap.get(id)).filter((item) => item !== undefined);
  const displayDetailPage = Math.min(detailPage, Math.max(1, Math.ceil(selectedPapers.length / 10)));
  const open = (value: Selection) => { setSelection(value); setDetailPage(1); };
  if (!scheme) return <InlineNotification kind="info" title="暂无学科体系数据" subtitle="尚未取得可供分析的分类关系。" hideCloseButton />;
  const external = scheme.scheme === 'INCITES_WOS';
  return <section className="sg-analysis-panel sg-discipline-workbench">
    <header className="sg-analysis-panel-heading"><div><Analytics size={24} /><span>
      <h2>学科方向分析</h2><p>按分类体系查看各方向的论文数量，以及同时涉及两个方向的论文。不同体系分别统计。</p>
    </span></div></header>
    <div className="sg-discipline-controls">
      <Dropdown id="discipline-system" titleText="分类体系与版本" label="选择体系" items={schemes}
        selectedItem={scheme} itemToString={(item) => item ? `${item.name} · ${item.version}` : ''}
        onChange={({ selectedItem }) => { if (selectedItem) { setSchemeKey(selectedItem.key); setQuery(''); setPage(1); setSelection(null); } }} />
      <Dropdown id="discipline-mode" titleText="查看内容" label="查看内容"
        items={[{ id: 'distribution', name: '各方向论文数量' }, { id: 'intersection', name: '方向交叉论文数量' }]}
        selectedItem={{ id: mode, name: mode === 'distribution' ? '各方向论文数量' : '方向交叉论文数量' }} itemToString={(item) => item?.name ?? ''}
        onChange={({ selectedItem }) => { if (selectedItem) { setMode(selectedItem.id); setPage(1); } }} />
      <Search id="discipline-search" labelText="搜索方向名称或代码" placeholder="搜索方向名称或代码" value={query}
        onChange={(event) => { setQuery(event.target.value); setPage(1); }} onClear={() => { setQuery(''); setPage(1); }} />
    </div>
    <div className="sg-discipline-summary">
      <div><span>论文分类覆盖</span><strong>{scheme.covered_publications}<small> / {workspace.publication_count} 篇</small></strong><span>覆盖 {percent(scheme.covered_publications, workspace.publication_count)}</span></div>
      <div><span>尚无该体系分类</span><strong>{scheme.missing_publications}<small> 篇</small></strong><span>未分类不代表不涉及该方向</span></div>
      <div><span>涉及研究方向</span><strong>{scheme.directions.length}<small> 个</small></strong><span>当前体系、当前版本</span></div>
      <div><span>涉及多个方向的论文</span><strong>{scheme.multiclass_publications}<small> 篇</small></strong><span>同一论文至少关联两个方向</span></div>
    </div>
    <p className="sg-discipline-explanation"><Information size={16} aria-hidden="true" /><span>
      分类结果用于表征论文的研究内容，不作为项目实际申报代码或学科归属的认定依据。各研究方向的论文数量分别去重，覆盖率以当前分析范围内的 {workspace.publication_count} 篇论文为基数计算。同一论文可关联多个研究方向，因此各方向覆盖率之和可能超过 100%。
    </span></p>
    {!scheme.directions.length ? <div className="sg-discipline-empty"><Information size={24} /><h3>当前范围暂无该体系的论文分类</h3><p>{scheme.dictionary_count ? `已收录 ${scheme.dictionary_count} 个字典条目，但尚无当前可用的论文关联。` : '当前没有可用的分类字典及论文关联。'}不会用其他体系的结果替代。</p></div>
      : <div className="sg-discipline-results">
        <header><h3>{mode === 'distribution' ? '各方向论文数量' : '方向交叉论文数量'}</h3><span>共 {total} 项{search ? '匹配结果' : ''}</span></header>
        {mode === 'intersection' && <p className="sg-discipline-explanation"><Information size={16} aria-hidden="true" /><span>统计同时涉及两个研究方向的论文数量。例如，一篇论文同时关联药学和生物医学工程，就计入“药学 × 生物医学工程”。每个组合内按论文去重，仅比较同一分类体系和版本；方向交叉不等同于已确认的跨学科合作。</span></p>}
        {!total ? <div className="sg-discipline-empty"><p>{search ? '没有匹配的方向，请更换关键词或清除搜索。' : '当前范围暂无同时涉及两个研究方向的论文。'}</p>{search && <Button kind="ghost" onClick={() => { setQuery(''); setPage(1); }}>清除搜索</Button>}</div>
          : <div className="sg-discipline-table-scroll"><Table size="lg" aria-label={mode === 'distribution' ? '学科方向覆盖分布' : '方向交叉论文数量'}><TableHead><TableRow>
            <TableHeader>{mode === 'distribution' ? '方向 / 分类代码' : '方向组合'}</TableHeader>
            {mode === 'distribution' && <><TableHeader>{external ? '分类来源' : '主 / 辅分类匹配论文数'}</TableHeader><TableHeader>关联学者 / 机构数</TableHeader></>}
            <TableHeader>论文数 / 覆盖率</TableHeader><TableHeader>论文依据</TableHeader>
          </TableRow></TableHead><TableBody>
            {mode === 'distribution' ? directions.slice(start, start + size).map((item) => <TableRow key={item.object_id} className="sg-direction-coverage-row" style={{ '--direction-share': `${(item.share ?? 0) * 100}%` } as CSSProperties}>
              <TableCell><strong>{item.name}</strong><small>{item.code ?? '代码未记录'}{item.level != null ? ` · ${item.level} 级` : ''}</small></TableCell>
              <TableCell>{external ? '外部标引' : <>{item.primary_publications} / {item.secondary_publications}{item.unspecified_publications > 0 && <small>角色未标注 {item.unspecified_publications} 篇</small>}</>}</TableCell>
              <TableCell>{item.scholar_count} / {item.organization_count}</TableCell>
              <TableCell>{item.publication_ids.length} 篇<small>{percent(item.publication_ids.length, workspace.publication_count)}</small></TableCell>
              <TableCell><Button kind="ghost" size="sm" onClick={() => open({ title: item.name, concepts: [item.object_id] })} aria-label={`查看${item.name}的论文依据`}>查看论文</Button></TableCell>
            </TableRow>) : intersections.slice(start, start + size).map((item) => {
              const title = `${lookup.get(item.left_id)?.name} × ${lookup.get(item.right_id)?.name}`;
              return <TableRow key={`${item.left_id}:${item.right_id}`}><TableCell><strong>{title}</strong></TableCell><TableCell>{item.publication_ids.length} 篇<small>{percent(item.publication_ids.length, workspace.publication_count)}</small></TableCell><TableCell><Button kind="ghost" size="sm" onClick={() => open({ title, concepts: [item.left_id, item.right_id] })}>查看共同论文</Button></TableCell></TableRow>;
            })}
          </TableBody></Table></div>}
        {total > 0 && <Pagination page={displayPage} pageSize={size} pageSizes={[20, 50, 100]} totalItems={total} itemsPerPageText="每页条数" backwardText="上一页" forwardText="下一页" onChange={({ page: next, pageSize }) => { setPage(next); setSize(pageSize); }} />}
      </div>}
    <DirectionExtensions workspace={workspace} scheme={scheme} dataVersion={dataVersion} />
    <Modal open={selection !== null} passiveModal size="lg" modalHeading={selection?.title ?? '论文依据'} modalLabel={`${scheme.name} · ${scheme.version}`} onRequestClose={() => setSelection(null)}>
      {selection && <div className="sg-direction-evidence">
        <p className="sg-discipline-explanation"><Information size={16} aria-hidden="true" /><span>共 {selectedPapers.length} 篇去重论文。学者与机构来自这些论文的作者及署名关系，不代表当前人事归属。以下仅展示所选方向的分类依据。</span></p>
        {selectedPapers.slice((displayDetailPage - 1) * 10, displayDetailPage * 10).map((paper) => <article key={paper.object_id}>
          <h4><Link to={`/outputs/${paper.object_id}`}>{paper.title}</Link></h4><p>{paper.year ?? '发表年份未收录'}</p>
          <details><summary>关联学者 {(paper.scholars ?? []).length} 位 · 署名机构 {(paper.organizations ?? []).length} 个</summary>
            <div className="sg-direction-entities">{(paper.scholars ?? []).length ? (paper.scholars ?? []).map((person) => <Link key={person.object_id} to={`/scholars/${person.object_id}`}>{person.name}</Link>) : '暂无关联学者'}</div>
            <div className="sg-direction-entities">{(paper.organizations ?? []).length ? (paper.organizations ?? []).map((org) => <Link key={org.object_id} to={`/institutions/${org.object_id}`}>{org.name}</Link>) : '暂无署名机构关系'}</div>
          </details>
          {scheme.evidence.filter((e) => e.publication_id === paper.object_id && selection.concepts.includes(e.concept_id)).map((e, i) => <div className="sg-direction-source" key={`${e.concept_id}:${i}`}>
            <strong>{lookup.get(e.concept_id)?.name}</strong><span>{roleLabel(e.role, scheme.scheme)} · {sourceLabel(e.source_kind)}</span>
            <p>{e.rationale.replace(/^(?:内容规则候选，尚未经专家核验；|AI读取全文摘要\/正文后的补充语义候选，尚未经专家核验；|AI抽查全文后修正候选，尚未经专家核验；)/, '') || '未保存分类理由。'}</p><details><summary>查看来源片段</summary><blockquote>{e.excerpt || '未保存来源片段，可打开论文详情查看全文。'}</blockquote></details>
          </div>)}
        </article>)}
        {selectedPapers.length > 10 && <Pagination page={displayDetailPage} pageSize={10} pageSizes={[10]} totalItems={selectedPapers.length} itemsPerPageText="每页论文" backwardText="上一页" forwardText="下一页" onChange={({ page: next }) => setDetailPage(next)} />}
      </div>}
    </Modal>
  </section>;
}
