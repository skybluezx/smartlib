import { useWorkbenchPreference } from './workbenchSettings';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Modal } from '@carbon/react';
import type { DirectionScheme, DisciplineWorkspace } from '../../generated/smartlib-api';
import './directionYearChart.css';

export function DirectionYearChart({ workspace, scheme }: { workspace: DisciplineWorkspace; scheme: DirectionScheme }) {
  const [coverage, setCoverage] = useWorkbenchPreference('direction.coverage', false);
  const [search, setSearch] = useWorkbenchPreference('direction.search', '');
  const [selected, setSelected] = useState<{ title: string; ids: string[] } | null>(null);
  const papers = new Map(workspace.papers.map(p => [p.object_id, p]));
  const dated = workspace.papers.map(p => p.year).filter((y): y is number => typeof y === 'number').sort((a,b) => a-b);
  const years: (number | null)[] = dated.length ? Array.from({length: (dated.at(-1) ?? 0) - (dated[0] ?? 0) + 1}, (_,i) => (dated[0] ?? 0)+i) : [];
  if (workspace.papers.some(p => p.year == null)) years.push(null);
  const totals = years.map(year => workspace.papers.filter(p => (p.year ?? null) === year).length);
  const rows = scheme.directions.map(d => ({ ...d, cells: years.map(year => [...new Set(d.publication_ids)].filter(id => papers.has(id) && (papers.get(id)?.year ?? null) === year)) }))
    .sort((a,b) => b.publication_ids.length - a.publication_ids.length);
  const maximum = Math.max(1, ...rows.flatMap(d => d.cells.map(c => c.length)));
  const shown = rows.filter(d => `${d.name} ${d.code ?? ''}`.toLowerCase().includes(search.trim().toLowerCase()));
  return <>
    <div className="sg-year-toolbar"><label>显示指标<select value={coverage ? 'coverage' : 'count'} onChange={e => setCoverage(e.target.value === 'coverage')}><option value="count">论文篇数</option><option value="coverage">当年论文覆盖率</option></select></label>
      <label>查找研究方向<input type="search" placeholder="输入方向名称或代码" value={search} onChange={e => setSearch(e.target.value)} /></label>
      <span className="sg-year-legend">少 <i /> 多</span></div>
    <p>横向比较同一方向的年度变化，纵向比较同一年的方向分布。覆盖率以当前范围当年全部论文为分母；同篇可涉及多个方向，合计可超过100%。灰格“—”表示该年无样本，不代表零产出。点击数字查看论文。</p>
    <p role="note">样本提示：请结合各年论文数阅读，小样本的高覆盖率不代表高潜力；最近年份可能尚未完整收录，不能直接判断增长或下降。</p>
    <div className="sg-year-matrix" role="region" aria-label="年度变化热力图" tabIndex={0}>
      <table><thead><tr><th scope="col">研究方向</th>{years.map(y => <th scope="col" key={y ?? 'unknown'}>{y ?? '年份未知'}</th>)}</tr></thead><tbody>
        <tr className="sg-year-totals"><th scope="row">范围内论文数</th>{totals.map((total,i) => <td key={years[i] ?? 'unknown'}>{total || '—'}</td>)}</tr>
        {shown.map(d => <tr key={d.object_id}><th scope="row">{d.name}<small>{d.code}</small></th>{d.cells.map((ids,i) => {
          const total = totals[i] ?? 0; const share = total ? ids.length / total : 0;
          const strength = coverage ? share : ids.length / maximum;
          const label = `${d.name} · ${years[i] ?? '年份未知'} · ${ids.length} 篇`;
          return <td key={years[i] ?? 'unknown'}>{!total ? <span className="sg-year-missing" title="当前范围该年没有论文样本">—</span> : <button type="button" aria-label={label} disabled={!ids.length} title={`${label}；当年覆盖率 ${(share*100).toFixed(1)}%`}
            style={{background: ids.length ? `rgba(0,125,121,${.08 + strength*.82})` : '#f4f4f4',color:strength>.6 ? '#fff':'#161616'}}
            onClick={() => setSelected({title:label,ids})}>{coverage ? `${(share*100).toFixed(1)}%` : ids.length}</button>}</td>;
        })}</tr>)}
      </tbody></table>
      {!shown.length && <p>没有符合条件的研究方向。</p>}
    </div>
    <Modal open={selected!==null} passiveModal modalHeading={selected?.title ?? '论文依据'} onRequestClose={()=>setSelected(null)}>
      <ul>{selected?.ids.map(id => <li key={id}><Link to={`/outputs/${id}`}>{papers.get(id)?.title ?? id}</Link></li>)}</ul>
    </Modal>
  </>;
}
