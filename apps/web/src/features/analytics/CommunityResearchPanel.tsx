import { useState } from 'react';
import { Button, Search, Select, SelectItem } from '@carbon/react';
import { Information } from '@carbon/icons-react';
import { Link } from 'react-router-dom';
import type { CommunityResearch } from '../../generated/smartlib-api';
import './communityResearch.css';

const basisNames = { funded: '项目资助成果', representative: '项目代表作' };
const schemeNames: Record<string, string> = { NSFC_APPLICATION_CODE: '国自然申请代码', INCITES_WOS: 'InCites / WoS研究方向', GBT_13745: 'GB/T学科分类', MOE_GRADUATE_DISCIPLINE: '教育部学科目录' };
export function CommunityResearchPanel({ research: r, papers, titles, initialScheme, entityName = '学者' }: { research: CommunityResearch; papers: string[]; titles: Map<string, string>; initialScheme?: string; entityName?: string }) {
  const schemes = [...new Set(r.directions.map(d => JSON.stringify([d.scheme,d.version])))].sort((a,b) => Number(b.includes('NSFC_APPLICATION_CODE'))-Number(a.includes('NSFC_APPLICATION_CODE')) || a.localeCompare(b));
  if (initialScheme && !schemes.includes(initialScheme)) schemes.push(initialScheme);
  const [scheme, setScheme] = useState(initialScheme ?? schemes[0] ?? '');
  const [basis, setBasis] = useState<'funded'|'representative'>('funded');
  const [view, setView] = useState<'funding'|'directions'|'cross'>('cross');
  const [search, setSearch] = useState('');
  const directions = r.directions.filter(d => JSON.stringify([d.scheme,d.version]) === scheme);
  const directionMap = new Map(directions.map(d => [d.key,d]));
  const funding = r.funding.filter(f => f.basis === basis);
  const fundingMap = new Map(funding.map(f => [f.key,f]));
  const classified = new Set(directions.flatMap(d => d.publication_ids));
  const total = new Set(papers).size;
  const share = (ids:string[]) => total ? `${(new Set(ids).size / total * 100).toFixed(1)}%` : '—';
  const matches = (name:string) => name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase());
  const evidence = (ids:string[]) => <details><summary>查看 {ids.length} 篇论文</summary><div className="sg-community-paper-evidence">{ids.map(id => <p key={id}><Link to={`/outputs/${id}`}>{titles.get(id) ?? id}</Link></p>)}</div></details>;
  const crosses = r.intersections.flatMap(x => { const f=fundingMap.get(x.funding_key), d=directionMap.get(x.direction_key); return f && d && matches(`${f.name} ${d.name} ${d.code}`) ? [{...x,f,d}] : []; });
  const shownFunding = funding.filter(f => matches(f.name));
  const shownDirections = directions.filter(d => matches(`${d.name} ${d.code}`));
  const count = view === 'cross' ? crosses.length : view === 'funding' ? shownFunding.length : shownDirections.length;
  return <section className="sg-community-research">
    <p className="sg-metric-note"><Information size={16}/><span>基于本簇 {total} 篇去重共同论文关联基金项目和研究方向，不改变分簇。分析对象为当前簇内{entityName}。{entityName === '机构' && '机构使用当前粒度与组合后的单位，层级关系不计合作。'}项目资助成果与项目代表作分别统计；论文致谢作为资助关系的来源证据；不据此认定本簇拥有这些项目或已获批。同一论文可关联多个种类和方向，各项覆盖率不可相加。分类不作为项目实际申报代码或正式学科归属。</span></p>
    <dl className="sg-community-research-summary">
      <div><dt>关联资助项目的论文</dt><dd>{r.funded_publication_ids.length} 篇</dd></div>
      <div><dt>作为项目代表作的论文</dt><dd>{r.representative_publication_ids.length} 篇</dd></div>
      <div><dt>未收录以上关联</dt><dd>{r.unlinked_publication_ids.length} 篇</dd></div>
    </dl>
    <div className="sg-community-research-controls">
      <Select id="community-research-basis" labelText="基金项目关联方式" value={basis} onChange={e=>setBasis(e.target.value as typeof basis)}>{Object.entries(basisNames).map(([key,name])=><SelectItem key={key} value={key} text={name}/>)}</Select>
      <Select id="community-research-scheme" labelText="分类体系与版本" value={scheme} disabled={!schemes.length} onChange={e=>setScheme(e.target.value)}>{!schemes.length && <SelectItem value="" text="暂无分类"/>}{schemes.map(key=>{ const d=r.directions.find(item=>JSON.stringify([item.scheme,item.version])===key); return <SelectItem key={key} value={key} text={d ? `${schemeNames[d.scheme] ?? d.scheme} · ${d.version}` : `${(JSON.parse(key) as string[]).join(' · ')}（本簇未收录）`}/>; })}</Select>
      <Search id="community-research-search" labelText="搜索基金或方向" placeholder="基金名称、方向或代码" value={search} onChange={e=>setSearch(e.target.value)}/>
    </div>
    <div className="sg-community-research-tabs" aria-label="合作簇交叉查看方式">{([['cross','基金项目 × 学科方向'],['funding','基金项目分布'],['directions','学科方向分布']] as const).map(([key,name])=><Button key={key} kind={view===key?'primary':'ghost'} size="sm" aria-pressed={view===key} onClick={()=>setView(key)}>{name}</Button>)}</div>
    <p>当前体系覆盖 {classified.size} / {total} 篇；未收录该体系分类 {total-classified.size} 篇。下表覆盖率均以本簇 {total} 篇论文为分母，不以已分类或已资助论文为分母。{view==='cross' && '交叉项要求同一篇论文同时具备两种关联。'}</p>
    <p>共 {count} 项{search.trim() ? '匹配结果' : ''}，完整列出，不截取前几项。未收录关联不等于未获资助或没有研究内容。</p>
    {!count ? <p role="status">当前条件下暂无关联记录，请更换关联方式、分类体系或搜索条件。</p> : <div className="sg-community-research-scroll" role="region" tabIndex={0} aria-label="基金项目与学科方向明细，可滚动"><table className="sg-people-table"><thead><tr>
      {view!=='directions' && <th>项目种类</th>}{view!=='funding' && <th>学科方向</th>}{view==='funding' && <th>关联项目</th>}{view==='directions' && <th>主 / 辅分类论文</th>}<th>论文数 / 簇内覆盖率</th><th>论文依据</th>
    </tr></thead><tbody>
      {view==='cross' && crosses.map(x=><tr key={`${x.funding_key}:${x.direction_key}`}><td>{x.f.name}</td><td>{x.d.name} {x.d.code}</td><td>{x.publication_ids.length} 篇 / {share(x.publication_ids)}</td><td>{evidence(x.publication_ids)}</td></tr>)}
      {view==='funding' && shownFunding.map(f=><tr key={f.key}><td>{f.name}</td><td><details><summary>{(f.project_ids ?? []).length} 个关联项目</summary><div className="sg-community-paper-evidence">{(f.project_ids ?? []).map(id=><p key={id}><Link to={`/outputs/${id}`}>{r.projects[id] ?? id}</Link></p>)}</div></details></td><td>{f.publication_ids.length} 篇 / {share(f.publication_ids)}</td><td>{evidence(f.publication_ids)}</td></tr>)}
      {view==='directions' && shownDirections.map(d=><tr key={d.key}><td>{d.name} {d.code}</td><td>{d.primary_publication_ids.length+d.secondary_publication_ids.length ? `${d.primary_publication_ids.length} / ${d.secondary_publication_ids.length}` : '—'}<small>仅统计已记录主辅角色的论文</small></td><td>{d.publication_ids.length} 篇 / {share(d.publication_ids)}</td><td>{evidence(d.publication_ids)}</td></tr>)}
    </tbody></table></div>}
    <details><summary>查看未收录记录与计算版本</summary><p>当前体系未收录分类：</p>{evidence(papers.filter(id=>!classified.has(id)))}<p>未收录基金项目关联：</p>{evidence(r.unlinked_publication_ids)}<p>{r.method_version} · <code>{r.input_hash}</code>；关系编号随“导出计算依据”一并保留。</p></details>
  </section>;
}
