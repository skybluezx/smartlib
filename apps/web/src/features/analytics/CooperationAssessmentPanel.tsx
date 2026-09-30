import { useSessionState } from './useSessionState';
import { FundingKindsExpansion } from './FundingKindsExpansion';
import { summarizeCommunityResearch } from './communityResearchSummary';
import { CommunityResearchPanel } from './CommunityResearchPanel';
import { InstitutionName, type InstitutionContext } from './InstitutionGranularityControls';
import { useState } from 'react';
import { Accordion, AccordionItem, Button, Pagination, Modal, Select, SelectItem } from '@carbon/react';
import { Information, Download, Analytics } from '@carbon/icons-react';
import { Link } from 'react-router-dom';
import type { CooperationAssessment, CollaborationNode, CooperationCommunity } from '../../generated/smartlib-api';

export function CooperationAssessmentPanel({ assessment: a, directory }: { assessment: CooperationAssessment; directory: CollaborationNode[] }) {
  const institution = a.entity_type === 'organization';
  const entityName = institution ? '机构' : '学者';
  const memberName = (id:string) => institution ? <InstitutionName id={id} name={names.get(id)??id} context={a.aggregation_context as InstitutionContext}/> : <Link to={`/scholars/${id}`}>{names.get(id)??id}</Link>;
  const [selected, setSelected] = useState<CooperationCommunity | null>(null);
  const [centerSelected, setCenterSelected] = useState<CooperationCommunity | null>(null);
  const [page, setPage] = useSessionState(`${a.entity_type}.assessmentPage`,1);
  const [researchScheme, setResearchScheme] = useSessionState(`${a.entity_type}.community.researchScheme`,'');
  const researchSchemes = [...new Set(a.communities.flatMap(c => c.research?.directions.map(d => JSON.stringify([d.scheme, d.version])) ?? []))].sort((x,y) => Number(y.includes('NSFC_APPLICATION_CODE')) - Number(x.includes('NSFC_APPLICATION_CODE')) || x.localeCompare(y));
  const effectiveScheme = researchSchemes.includes(researchScheme) ? researchScheme : researchSchemes[0] ?? '';
  const schemeNames: Record<string,string> = { NSFC_APPLICATION_CODE:'国自然申请代码', MOE_GRADUATE_DISCIPLINE:'教育部学科目录', INCITES_WOS:'InCites / WoS研究方向', GBT_13745:'GB/T学科分类' };
  const [researchSelected, setResearchSelected] = useState<CooperationCommunity | null>(null);
  const names = new Map(directory.map((p) => [p.object_id, p.name]));
  const titles = new Map(a.publications.map((p) => [String(p.publication_id), typeof p.title === "string" ? p.title : "题名尚未收录"]));
  const safePage = Math.min(page, Math.max(1, Math.ceil(a.communities.length / 10)));
  const exportEvidence = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ exported_at: new Date().toISOString(), assessment: a, directory }, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `cooperation-${a.input_hash.slice(0, 12)}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <section className="sg-cooperation-assessment">
    <header><div className="sg-assessment-heading"><Analytics size={24} /><div><h3>合作结构分析</h3><p>基于当前论文范围的全部合作关系识别群体；分簇结果不受图谱显示数量与探索筛选影响。</p></div></div><Button size="sm" kind="tertiary" renderIcon={Download} onClick={exportEvidence}>导出计算依据</Button></header>
    <dl className="sg-assessment-metrics">
      <div><dt>范围论文</dt><dd>{a.scope_publication_ids.length}</dd></div>
      <div><dt>关联{entityName}</dt><dd>{a.node_count}</dd></div>
      <div><dt>全部合作关系</dt><dd>{a.edge_count}</dd></div>
      <div><dt>识别合作簇</dt><dd>{a.communities.length}</dd></div>
      <div><dt>孤立{entityName}</dt><dd>{a.isolated_node_count}</dd></div>
      <div><dt>{institution ? '未归入当前粒度的论文' : '缺少作者关系的论文'}</dt><dd>{a.missing_author_publication_ids.length}</dd></div>
    </dl>
    <p className="sg-metric-note"><Information size={16} />仅作为当前样本的合作结构依据，不认定{institution ? '正式机构联盟' : '正式团队'}，不以簇大小、密度或模块度直接评价科研质量。学校完整成果与历年数据尚不完备，不能据此推断全校合作格局。</p>
    <Accordion className="sg-assessment-method"><AccordionItem title="算法、稳定性与统计口径">
      <p>标准 Louvain · NetworkX {a.library_version} · 分辨率 1 · 随机种子 42 · 收敛阈值 10⁻⁷。合作权重为去重共同论文数，至少共同 1 篇；不做开方，不截取前若干条边。模块度：{a.modularity == null ? '不适用（无合作边）' : a.modularity.toFixed(4)}；连通分量：{a.connected_component_count}。</p>
      <p>密度＝簇内实际合作对数÷可能合作对数；内部联系权重占比＝簇内合作权重的两倍÷该簇全部节点的加权度之和。稳定性为更换四个随机种子后，与最相似群体的成员 Jaccard 相似度均值，不是准确率或置信度。</p>
      <p>敏感性检查使用种子 43—46、分辨率 0.8/1.2，并对多{institution ? '机构' : '作者'}论文采用每篇 1/({institution ? '机构数' : '作者数'}−1) 的边权重重新计算。ARI 越接近 1，划分越一致；不设置未经验证的合格线。</p>
      <table className="sg-people-table"><thead><tr><th>检查项</th><th>取值</th><th>簇数</th><th>与基准划分 ARI</th></tr></thead><tbody>{a.sensitivity.map((r, i) => <tr key={i}><td>{r.kind === 'seed' ? '随机种子' : r.kind === 'resolution' ? '分辨率' : (institution ? '机构组规模校正' : '作者组规模校正')}</td><td>{String(r.value)}</td><td>{String(r.community_count)}</td><td>{Number(r.adjusted_rand_index).toFixed(4)}</td></tr>)}</tbody></table>
      {a.warnings.map((w) => <p key={w}>{w}</p>)}
      <p>成果指标以本簇共同论文为单位去重（{institution ? '至少两个簇内机构；孤立机构采用本机构论文' : '至少两名簇内作者；孤立人员采用个人论文'}）。同一论文可支撑多个簇，因此不能将各簇论文数或被引总量相加作为全范围总量。均值、中位数和比例仅使用该项有值的论文，缺失或冲突值不计为零。CNCI、JNCI、Collab-CNCI 采用逐篇指标算术平均，不用被引总和除以预期总和。</p>
      <p>JCR 影响因子及分区、中科院分区仅使用同年期刊文件；多分类按类别等权分摊，每篇总权重为 1。InCites 来源 JIF 单独展示，不补填 JCR 缺失。预期被引频次仅为基准背景；不计算影响因子总分，不用 JIF 或引文指标直接认定科研质量。</p>
      <p>中心{entityName}候选基于完整簇内网络：加权度（共同论文权重之和）与无权、归一化介数中心性分别取前 5%，且至少达到该项簇内中位数的 1.2 倍，保留并列并合并候选；该规则是探索性筛选，不是经验证的{institution ? '牵头单位' : '负责人'}认定标准。所有成员同值时不指定该类中心；孤立节点不指定中心。介数按最少合作步数计算，不把合作强度当作距离，不受图中连线截取影响。</p>
      <p>InCites 统计截止：{(a.metric_context?.incites_release as { indexed_through?: string } | null)?.indexed_through ?? '暂无来源快照'}；指标输入指纹：<code>{a.metric_input_hash ?? '暂无'}</code>。所有指标均为当前样本描述，不能外推完整团队绩效。</p>
      <p>方法版本：{a.method_version}；输入与参数指纹：<code>{a.input_hash}</code>。导出文件保留全部范围论文编号、{institution ? '署名机构输入' : '作者输入'}、分簇成员及敏感性结果，可用于复算。</p>
      {a.missing_author_publication_ids.map((id) => <p key={id}>{institution ? '缺少机构关系' : '缺少作者关系'}：<Link to={`/outputs/${id}`}>{id}</Link></p>)}
    </AccordionItem></Accordion>
    {<div className="sg-community-comparison-settings">
      <Select id="community-summary-scheme" labelText="合作簇对比：学科分类体系与版本" value={effectiveScheme} disabled={!researchSchemes.length} onChange={e => setResearchScheme(e.target.value)}>
        {!researchSchemes.length && <SelectItem value="" text="未收录分类"/>}{researchSchemes.map(key => { const [system = '',version = ''] = JSON.parse(key) as string[]; return <SelectItem key={key} value={key} text={`${schemeNames[system] ?? system} · ${version}`}/>; })}
      </Select>
      <p className="sg-metric-note"><Information size={16}/><span>新增覆盖率均以本簇去重共同论文数为分母。项目数仅统计资助关系中的具体项目，不混入代表作项目；同一项目跨种类只计一次。学科指标按所选体系与版本计算；主要方向展示并列第一，同篇多方向不等于跨学科创新。资助 × 学科覆盖率要求同一论文同时具备两类关联。未收录不等于实际不存在，不据此认定项目归属或申报成功率。</span></p>
    </div>}
    <div className="sg-people-table-wrap sg-community-summary-table" role="region" aria-label="合作簇指标表，可横向滚动" tabIndex={0}><table className="sg-people-table"><thead><tr><th>合作簇</th><th>全部成员</th><th>共同论文</th><th>内部联系 / 对外联系</th><th>密度</th><th>内部联系权重占比</th><th>成员稳定性</th><th>中心{entityName}候选</th><th>JIF 均值 / 中位数</th><th>CNCI 均值 / 中位数</th><th>被引总量</th><th>成果指标</th>{<><th>资助 / 代表作覆盖</th><th>资助项目 / 种类数</th><th>学科分类覆盖</th><th>主要研究方向</th><th>同篇多方向</th><th>资助 × 学科覆盖</th><th>基金项目与学科方向</th></>}<th>证据</th></tr></thead><tbody>{a.communities.slice((safePage - 1) * 10, safePage * 10).map((c) => <tr key={c.community_id}>
      <td>簇 {c.community_id + 1}{c.connected_components > 1 && <p>内部含 {c.connected_components} 个连通分量，需核实</p>}{c.member_ids.length === 1 && <p>孤立{entityName}</p>}</td><td>{c.member_ids.length}</td><td>{c.publication_ids.length}{c.member_ids.length === 1 && (institution ? '（机构论文）' : '（个人论文）')}</td><td>{c.internal_edge_count} / {c.external_edge_count}</td><td>{c.member_ids.length < 2 ? '不适用' : `${(c.density * 100).toFixed(1)}%`}</td><td>{c.internal_weight_share == null ? '不适用' : `${(c.internal_weight_share * 100).toFixed(1)}%`}</td><td>{c.seed_stability.toFixed(3)}</td>
      <td className="sg-community-centers">{c.centers?.length ? <><span>{`展示 ${Math.min(3,c.centers.length)} / ${c.centers.length} ${institution ? '个' : '位'}重点候选`}</span>{c.centers.slice(0, 3).map(n => <p key={n.person_id}>{memberName(n.person_id)}<small>{n.roles.join(' · ')}</small></p>)}<Button kind="ghost" size="sm" onClick={() => { setSelected(null); setCenterSelected(c); }}>查看中心依据</Button></> : '未形成明显中心'}</td>
      <td><MetricCell community={c} code="journal.jif" /></td><td><MetricCell community={c} code="incites.cnci" /></td><td><MetricCell community={c} code="incites.times_cited" total /></td><td><Button kind="ghost" size="sm" onClick={() => { setCenterSelected(null); setSelected(c); }}>查看全部指标</Button></td>{<><ResearchSummaryCells community={c} scheme={effectiveScheme}/><td><Button kind="ghost" size="sm" disabled={!c.research} onClick={()=>setResearchSelected(c)}>查看分布与交叉</Button></td></>}<td><details><summary>成员与论文</summary>{c.member_ids.map((id) => <p key={id}>{memberName(id)}</p>)}{c.publication_ids.map((id) => <p key={id}><Link to={`/outputs/${id}`}>{titles.get(id) ?? id}</Link></p>)}</details></td>
    </tr>)}</tbody></table></div>
    <Modal open={selected !== null} passiveModal size="lg" modalHeading={`簇 ${(selected?.community_id ?? 0) + 1} · 成果指标`} onRequestClose={() => setSelected(null)}>
      {selected && <div className="sg-community-detail">
        <p className="sg-metric-note"><Information size={16} />{selected.publication_ids.length} 篇去重论文；各指标仅在有值论文中计算，覆盖不足不代表表现为零。比例按各项有效论文数计算。</p>
        <h4>期刊与论文影响指标</h4>
        <div className="sg-people-table-wrap"><table className="sg-people-table"><thead><tr><th>指标</th><th>覆盖 / 簇论文</th><th>均值</th><th>中位数</th><th>最小—最大</th><th>补充统计</th><th>论文依据</th></tr></thead><tbody>
          {(selected.metrics ?? []).map(m => <tr key={m.code}><td>{m.label}</td><td>{m.count} / {selected.publication_ids.length}</td><td>{format(m.mean)}</td><td>{format(m.median)}</td><td>{format(m.minimum)}—{format(m.maximum)}</td><td>{m.total != null ? `被引总量 ${format(m.total)}` : m.reference != null && m.count > 0 ? `高于 1：${m.above_reference_count} 篇（${((m.above_reference_count ?? 0) / m.count * 100).toFixed(1)}%）` : '—'}</td><td><details><summary>查看有值与缺失</summary>{m.publication_ids.map(id => <p key={id}><Link to={`/outputs/${id}`}>{titles.get(id) ?? id}</Link></p>)}<p>缺失或冲突：{m.missing_publication_ids.length} 篇</p>{m.missing_publication_ids.map(id => <p key={id}><Link to={`/outputs/${id}`}>{titles.get(id) ?? id}</Link></p>)}</details></td></tr>)}
        </tbody></table></div>
        <h4>同年分区构成</h4><p>每篇论文按分类等权分摊；比例以该体系有分区的论文数为分母。未匹配的论文不参与比例计算。</p>
        {Object.entries(selected.quartiles ?? {}).map(([system, q]) => <div key={system}><h5>{system === 'jcr' ? 'JCR 分区' : '中科院分区'} · 覆盖 {q.count} / {selected.publication_ids.length} 篇</h5><div className="sg-community-quartiles">{['Q1','Q2','Q3','Q4'].map((key, i) => <div key={key}><strong>{system === 'jcr' ? key : `${i + 1} 区`}</strong><span>{q.shares[key] == null ? '暂无数据' : `${(q.shares[key] * 100).toFixed(1)}%`}</span><small>{q.count ? `${format(q.paper_equivalents[key])} 等效篇数` : '缺少同年分区'}</small></div>)}</div></div>)}
      </div>}
    </Modal>
    <Modal open={centerSelected !== null} passiveModal size="lg" modalHeading={`簇 ${(centerSelected?.community_id ?? 0) + 1} · 中心${entityName}依据`} onRequestClose={() => setCenterSelected(null)}>
      {centerSelected && <div className="sg-community-detail">
        <h4>中心{entityName}候选及依据</h4><p>分别依据簇内合作加权度和介数中心性筛选{centerSelected.centers_method === 'top-5pct-median-1.2-v2' ? '前 5%，且至少达到该项簇内中位数的 1.2 倍' : '前 10%（历史规则）'}，包含并列；仅为结构候选，不认定{institution ? '牵头单位' : '团队负责人'}。所有成员同值时不强行选出中心。</p>
        {centerSelected.centers?.length ? <table className="sg-people-table"><thead><tr><th> {entityName}</th><th>入选依据</th><th>簇内合作{entityName}数</th><th>合作权重</th><th>介数中心性</th></tr></thead><tbody>{centerSelected.centers.map(n => <tr key={n.person_id}><td>{memberName(n.person_id)}</td><td>{n.roles.join(' · ')}</td><td>{n.internal_degree}</td><td>{format(n.internal_strength)}</td><td>{n.betweenness.toFixed(4)}</td></tr>)}</tbody></table> : <p>当前簇未识别出突出中心候选，或为孤立{entityName}。</p>}
        {<><h4>全体成员结构指标</h4><p>以下保留全部成员，不因候选筛选而删除。20%差异为暂行展示规则，不是统计显著性或科研评价合格线。上方汇总表优先展示两项均入选者，再按两项各自归一化后较高值排序，最多展示3个候选；下表列出全部成员。</p>{centerSelected.member_center_metrics?.length ? <div className="sg-community-member-metrics" role="region" aria-label="全体成员中心性指标，可滚动" tabIndex={0}><table className="sg-people-table"><thead><tr><th>{entityName}</th><th>入选依据</th><th>簇内合作{entityName}数</th><th>合作权重</th><th>介数中心性</th></tr></thead><tbody>{centerSelected.member_center_metrics.map(n=><tr key={n.person_id}><td>{memberName(n.person_id)}</td><td>{n.roles.join(' · ') || '未入选'}</td><td>{n.internal_degree}</td><td>{format(n.internal_strength)}</td><td>{n.betweenness.toFixed(4)}</td></tr>)}</tbody></table></div> : <p>此历史结果未记录全体成员指标，请重新分析。</p>}</>}
      </div>}
    </Modal>
    <Modal open={researchSelected !== null} passiveModal size="lg" modalHeading={`簇 ${(researchSelected?.community_id ?? 0)+1} · 基金项目与学科方向`} onRequestClose={()=>setResearchSelected(null)}>
      {researchSelected?.research && <CommunityResearchPanel key={researchSelected.community_id} entityName={entityName} initialScheme={effectiveScheme} research={researchSelected.research} papers={researchSelected.publication_ids} titles={titles}/>}
    </Modal>
    <Pagination page={safePage} pageSize={10} pageSizes={[10]} totalItems={a.communities.length} itemsPerPageText="每页合作簇" onChange={({ page: p }) => setPage(p)} />
  </section>;
}


function format(value: number | null | undefined) {
  return value == null ? '暂无数据' : value.toLocaleString('zh-CN', { maximumFractionDigits: 3 });
}
function MetricCell({ community, code, total = false }: { community: CooperationCommunity; code: string; total?: boolean }) {
  const m = community.metrics?.find(v => v.code === code);
  return <>{total ? format(m?.total) : `${format(m?.mean)} / ${format(m?.median)}`}<small className="sg-community-coverage">覆盖 {m?.count ?? 0} / {community.publication_ids.length} 篇</small></>;
}

function ResearchSummaryCells({ community: c, scheme }: { community: CooperationCommunity; scheme: string }) {
  if (!c.research) return <>{Array.from({length:6},(_,i)=><td key={i}>此结果未记录</td>)}</>;
  const m = summarizeCommunityResearch(c.research,c.publication_ids,scheme);
  const ratio = (n:number) => m.total ? `${(n/m.total*100).toFixed(1)}%` : '—';
  const coverage = (n:number) => <><strong>{ratio(n)}</strong><small className="sg-community-coverage">{n} / {m.total} 篇</small></>;
  return <>
    <td>资助 {ratio(m.funded)}<small className="sg-community-coverage">{m.funded} / {m.total} 篇</small>代表作 {ratio(m.representative)}<small className="sg-community-coverage">{m.representative} / {m.total} 篇</small></td>
    <td><strong>{m.projects} / {m.kinds}</strong><small className="sg-community-coverage">个项目 / 已登记种类</small>{m.untyped > 0 && <small className="sg-community-coverage">{m.untyped} 个项目未登记种类</small>}<FundingKindsExpansion rows={m.categoryCounts} missing={m.missingCategoryCount}/></td>
    <td>{coverage(m.classified)}<small className="sg-community-coverage">{m.directionCount} 个方向；{m.total-m.classified} 篇未收录</small></td>
    <td className="sg-community-leading-direction">{m.leading.length ? <>{m.leading.join('、')}{m.leading.length > 1 && <small className="sg-community-coverage">并列第一</small>}<small className="sg-community-coverage">各 {m.leadingCount} 篇 · {ratio(m.leadingCount)}</small></> : '未收录方向'}</td>
    <td>{m.classified ? coverage(m.multiple) : '—'}<small className="sg-community-coverage">{m.classified ? '同篇关联至少两个方向' : '未收录分类，无法判断'}</small></td>
    <td>{m.classified ? coverage(m.cross) : '—'}<small className="sg-community-coverage">{m.classified ? '资助论文且有该体系分类' : '未收录分类，无法判断'}</small></td>
  </>;
}
