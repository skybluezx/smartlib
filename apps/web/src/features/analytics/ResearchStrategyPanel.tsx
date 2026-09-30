import { useState } from 'react';
import { Accordion, AccordionItem, Button, Dropdown, InlineNotification, Modal, Tab, TabList, TabPanel, TabPanels, Tabs } from '@carbon/react';
import { Link } from 'react-router-dom';
import type { CollaborationOutcomes, OutcomePaper } from '../../generated/smartlib-api';
import { CollaborationOutcomesPanel } from './CollaborationOutcomesPanel';
import { comparePapers, dimensions, labels, partnerProfiles, type StrategySettings } from './strategyAnalysis';
import { PlanningRegister } from './PlanningRegister';

const fmt = (v: number | null) => v == null ? '未覆盖' : v.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
export function ResearchStrategyPanel({ data, settings, onSettings, historical = false }: { historical?: boolean; data: CollaborationOutcomes; settings: StrategySettings; onSettings: (s: StrategySettings) => void }) {
  const [evidence, setEvidence] = useState<{ title: string; papers: OutcomePaper[] } | null>(null);
  const [tab, setTab] = useState(0);
  const organizations = Object.assign({}, ...data.papers.map(p => p.institution_name_by_id ?? {})) as Record<string, string>;
  const schemes = [...new Set(['研究主题', 'NSFC_APPLICATION_CODE', 'MOE_GRADUATE_DISCIPLINE', 'GBT_13745', ...data.papers.flatMap(p => (p.disciplines ?? []).map(d => d.scheme))])].sort();
  const comparisons = comparePapers(data.papers, settings);
  const partners = partnerProfiles(data.papers, settings.focal);
  const directions = comparePapers(data.papers, { ...settings, primary: '研究方向', secondary: '不交叉' });
  const total = data.papers.length;
  const coverage: {name: string; papers: OutcomePaper[]; note: string}[] = [
    {name:'完整作者机构对应',papers:data.papers.filter(p => p.mode !== '机构或作者信息不完整'),note:'用于署名结构分析；不等于人事归属。'},
    {name:'完整国家或地区信息',papers:data.papers.filter(p => !labels(p, '合作地域', settings).includes('地域信息不足')),note:'缺少结构化国家信息时不从机构名称推断。'},
    {name:'至少一项有证据作者角色',papers:data.papers.filter(p => p.affiliations?.some(a => a.roles?.length)),note:'仅署名排序不证明共同第一、通讯或共同主导。'},
    {name:'CNCI 指标',papers:data.papers.filter(p => p.cnci != null),note:'仅使用本次指定的单一 InCites 发布版本。'},
    {name:'同年 JIF（内部参考）',papers:data.papers.filter(p => p.impact_factor != null),note:'按论文发表年份匹配已发布指标，含内部暂用资料；无匹配不等于影响力为零。'},
    ...['NSFC_APPLICATION_CODE', 'MOE_GRADUATE_DISCIPLINE', 'GBT_13745', 'INCITES_WOS'].map(s => ({name:s,papers:data.papers.filter(p => p.disciplines?.some(d => d.scheme === s)),note:'按原体系标识独立统计；不将不同体系视为等价映射。'})),
  ];
  return <section className="sg-strategy-workbench">
    <div className="sg-strategy-controls">
      <Dropdown id="strategy-focal" titleText="本校 / 观察机构" label="请选择，用于贡献与伙伴分析" items={Object.keys(organizations).sort((a, b) => (organizations[a] ?? a).localeCompare(organizations[b] ?? b))} itemToString={id => id ? organizations[id] ?? id : ''} selectedItem={settings.focal || null} onChange={({ selectedItem }) => onSettings({ ...settings, focal: selectedItem ?? '' })} />
      <Dropdown id="strategy-scheme" titleText="学科体系（保留原始版本标识）" label="选择体系" items={schemes} selectedItem={settings.scheme} onChange={({ selectedItem }) => onSettings({ ...settings, scheme: selectedItem ?? settings.scheme })} />
    </div>
    <Tabs selectedIndex={tab} onChange={({selectedIndex}) => setTab(selectedIndex)}><TabList aria-label="科研管理专题"><Tab>合作比较</Tab><Tab>伙伴与持续性</Tab><Tab>研究方向</Tab><Tab>申请与成长</Tab><Tab>支持与复盘</Tab><Tab>数据可用性</Tab></TabList><TabPanels>
      <TabPanel><h3>交叉比较</h3><p>同一范围内的去重论文；多方向论文可进入多个方向组，各组之和可能超过总数。</p>
        <div className="sg-strategy-controls">
          <Dropdown id="strategy-primary" titleText="分组维度" label="选择维度" items={[...dimensions]} selectedItem={settings.primary} onChange={({selectedItem}) => onSettings({...settings, primary:selectedItem ?? settings.primary})} />
          <Dropdown id="strategy-secondary" titleText="交叉维度" label="不交叉" items={['不交叉', ...dimensions] as const} selectedItem={settings.secondary} onChange={({selectedItem}) => onSettings({...settings, secondary:selectedItem ?? '不交叉'})} />
          <Dropdown id="strategy-metric" titleText="比较指标" label="CNCI" items={['CNCI', '被引次数', '同年 JIF'] as const} selectedItem={settings.metric} onChange={({selectedItem}) => onSettings({...settings, metric:selectedItem ?? 'CNCI'})} />
        </div>
        <div className="sg-outcomes-table"><table className="cds--data-table"><thead><tr>{['比较组', '去重论文', `${settings.metric} 中位数`, '指标覆盖 / 组内分母', '依据'].map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{comparisons.map(g => <tr key={g.key}><td>{g.label}</td><td>{g.papers.length}</td><td>{fmt(g.median)}</td><td>{g.covered} / {g.papers.length}</td><td><Button kind="ghost" size="sm" onClick={() => setEvidence({title:g.label,papers:g.papers})}>查看论文</Button></td></tr>)}</tbody></table></div>
        {!comparisons.length && <p>该范围暂无论文，请调整分析范围。</p>}
        <Accordion><AccordionItem title="指标含义与比较边界"><p>CNCI 为来源提供的规范化引文指标；被引次数受时间窗口影响；JIF 为发表载体指标，不代表单篇质量。分母为本组去重论文，缺失不补零。未控制领域、年份和文献类型时不作质量排名；可选择年份或文献类型进行交叉分层，小样本仅作案例观察。</p><p>本校第一与通讯角色可同时存在；角色展示只描述现有证据，不将未记录角色当作否定。跨学科分类反映论文涉及的方向，不证明作者团队实现跨学科合作。</p></AccordionItem></Accordion>
        <Accordion><AccordionItem title="署名结构基线与分页明细"><CollaborationOutcomesPanel data={data} /></AccordionItem></Accordion>
      </TabPanel>
      <TabPanel><h3>合作伙伴与持续性</h3><p>仅观察当前样本的共同署名与覆盖年份，不将共同论文数当作合作质量评分。年度缺口可能来自代表作抽样。</p>
        {!settings.focal ? <p>请先在上方选择本校或观察机构。</p> : !partners.length ? <p>当前范围没有可识别的外部共同署名机构。</p> : <div className="sg-outcomes-table"><table className="cds--data-table"><thead><tr>{['伙伴', '共同论文', '有成果年份', '占观察机构样本', 'CNCI 中位数', '依据'].map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{partners.map(p => <tr key={p.id}><td><Link to={`/institutions/${p.id}`}>{p.name}</Link></td><td>{p.papers.length}</td><td>{p.years.join('、') || '年份未收录'}</td><td>{p.share == null ? '未覆盖' : `${(p.share * 100).toFixed(1)}%`}</td><td>{fmt(p.median)}</td><td><Button kind="ghost" onClick={() => setEvidence({title:p.name,papers:p.papers})}>查看共同成果</Button></td></tr>)}</tbody></table></div>}
        <InlineNotification kind="info" title="尚不输出合作质量综合评分" subtitle="完整历史成果、稳定身份、贡献及方法能力证据尚未齐备。当前比例仅描述样本集中度，不能等同实际依赖程度。" hideCloseButton />
      </TabPanel>
      <TabPanel><h3>研究方向积累</h3><p>按所选分类体系逐方向查看时间分布、学者、机构与论文。不同体系不合并打分；暂无外部基准，不判断全球热点或国际领先。</p>
        <div className="sg-outcomes-table"><table className="cds--data-table"><thead><tr>{['方向', '论文', '年度分布', '关联学者 / 根机构', '观察边界', '依据'].map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{directions.map(g => {
          const years = new Map<string, number>(); for (const p of g.papers) { const y = String(p.publication_year ?? '未知'); years.set(y, (years.get(y) ?? 0) + 1); }
          const people = new Set(g.papers.flatMap(p => p.affiliations?.map(a => a.person_id) ?? []));
          const orgs = new Set(g.papers.flatMap(p => p.institution_ids ?? []));
          return <tr key={g.key}><td>{g.label}</td><td>{g.papers.length}</td><td>{[...years].sort().map(([y,n]) => `${y}：${n}`).join('；')}</td><td>{people.size} / {orgs.size}</td><td>{g.papers.length < 5 ? '小样本，继续观察' : '有样本积累，待专家研判'}</td><td><Button kind="ghost" onClick={() => setEvidence({title:g.label,papers:g.papers})}>查看支撑记录</Button></td></tr>;
        })}</tbody></table></div>
        {!directions.length && <p>当前范围暂无可用方向数据。</p>}
      </TabPanel>
      <TabPanel>{historical ? <p>历史快照不读取当前申请台账。</p> : <PlanningRegister mode="applications" active={tab === 3} />}</TabPanel>
      <TabPanel>{historical ? <p>历史快照不读取当前支持与复盘台账。</p> : <PlanningRegister mode="actions" active={tab === 4} />}</TabPanel>
      <TabPanel><h3>当前分析范围的数据可用性</h3><p>以本次 {total} 篇去重论文为分母。覆盖数为0表示没有可用记录，不代表指标值为0。</p><table className="cds--data-table"><thead><tr><th>数据项</th><th>可用 / 范围</th><th>边界及补充要求</th><th>逐篇核对</th></tr></thead><tbody>{coverage.map(c => <tr key={c.name}><td>{c.name}</td><td>{c.papers.length} / {total}</td><td>{c.note}</td><td><Button kind="ghost" onClick={() => setEvidence({title:`${c.name} · 已覆盖`,papers:c.papers})}>已覆盖</Button><Button kind="ghost" onClick={() => setEvidence({title:`${c.name} · 待补充`,papers:data.papers.filter(p => !c.papers.includes(p))})}>待补充</Button></td></tr>)}</tbody></table><p>完整历史成果、完整申请分母和外部对标数据尚未接入。研究方向潜力、申报成功率和支持效果因果判断暂不开放。</p></TabPanel>
    </TabPanels></Tabs>
    <Modal open={evidence !== null} passiveModal size="lg" modalHeading={evidence?.title ?? '分析依据'} onRequestClose={() => setEvidence(null)}>
      <p>{evidence?.papers.length ?? 0} 篇去重论文；可进入详情查看全文、作者与关系来源。</p>
      {evidence?.papers.map(p => <article className="sg-strategy-evidence" key={p.publication_id}><h4><Link to={`/outputs/${p.publication_id}`}>{p.title}</Link></h4><p>{p.publication_year ?? '年份未知'} · {p.mode}</p><details><summary>人员、机构、项目及关系状态</summary>{p.affiliations?.map(a => <p key={a.relation_id}><Link to={`/scholars/${a.person_id}`}>{a.person_name}</Link> · <Link to={`/institutions/${a.organization_id}`}>{a.organization_name}</Link> · {a.roles?.length ? a.roles.join('、') : '角色待补证据'} · {a.review_state === 'pending' ? '待核验' : a.review_state} · 关系编号 <code>{a.relation_id}</code></p>)}{p.projects?.map(project => <p key={project.relation_id}><Link to={`/outputs/${project.object_id}`}>{project.name}</Link> · {project.predicate === 'project.has_representative_publication' ? '申请代表作关系（不等于项目产出）' : '项目资助成果'} · {project.review_state === 'pending' ? '待核验' : project.review_state}</p>)}</details></article>)}
    </Modal>
  </section>;
}
