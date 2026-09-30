import { useId, useState } from 'react';
import { Information } from '@carbon/icons-react';
import { Checkbox, Select, SelectItem } from '@carbon/react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { runtimeConfig } from '../../shared/config/runtime';

interface Profile {
  object_type: string; total_papers: number; start_year: number | null; end_year: number | null;
  coverage: Record<string, number>;
  rows: { scheme: string; scheme_version: string; code: string; name: string; paper_count: number;
    primary_paper_count: number; publication_ids: string[]; pending_publication_ids?: string[]; source_kinds: string[] }[];
  papers: { publication_id: string; title: string; year: number | null }[];
}
const schemes = { NSFC_APPLICATION_CODE: '科研方向（国自然）', MESH: '具体主题（MeSH）', INCITES_WOS: '评价对照（InCites）', MOE_GRADUATE_DISCIPLINE: '学科建设（教育部）' };
const sources: Record<string, string> = { algorithmic_inference: '系统推断', external_indexing: '外部数据库标引', human_classification: '人工分类' };

export function ResearchProfilePanel({ objectId, title }: { objectId: string; title?: string }) {
  const controlId = useId();
  const [scheme, setScheme] = useState('NSFC_APPLICATION_CODE');
  const [all, setAll] = useState(false);
  const [recent, setRecent] = useState(false);
  const query = useQuery({
    queryKey: ['research-profile', objectId, recent],
    queryFn: async ({ signal }) => {
      const range = recent ? `?start_year=${new Date().getFullYear() - 4}&end_year=${new Date().getFullYear()}` : '';
      const response = await fetch(`${runtimeConfig.apiBaseUrl.replace(/\/$/, '')}/api/v1/catalog/objects/${objectId}/research-profile${range}`, { signal, credentials: 'same-origin' });
      if (!response.ok) throw new Error('研究方向画像暂时无法读取');
      return response.json() as Promise<{ profile: Profile | null }>;
    },
    retry: 1,
  });
  const p = query.data?.profile;
  const rows = p?.rows.filter((r) => r.scheme === scheme) ?? [];
  return <section id="research-profile" aria-label="研究方向画像" className="sg-output-section sg-detail-section sg-research-profile">
    <header><h2>{title ?? (p?.object_type === 'project' ? '代表作主要研究什么' : '论文主要研究什么')}</h2><p>按论文汇总研究方向，展开方向可查看支撑论文。</p></header>
    <div className="sg-research-profile-controls">
      <Select id={`${controlId}-scheme`} labelText="分类口径" value={scheme} onChange={(e) => { setScheme(e.target.value); setAll(false); }}>{Object.entries(schemes).map(([key, label]) => <SelectItem key={key} value={key} text={label} />)}</Select>
      <Checkbox id={`${controlId}-recent`} labelText="只看近五年论文" checked={recent} onChange={(_, { checked }) => setRecent(checked)} />
    </div>
    {query.isPending ? <p>正在读取画像…</p> : query.isError ? <div role="alert"><p>研究方向画像暂时无法读取，请稍后重试。</p><button type="button" onClick={() => void query.refetch()}>重新读取画像</button></div> : !p ? <p>所选范围暂无可用于画像的论文。</p> : <>
      {p.object_type === 'organization' && <p className="sg-research-profile-notice"><Information size={16} aria-hidden="true" /><span>本画像仅统计论文中明确署名于本机构的成果，不把关联学者的全部历史成果计入；与下方“关联学者与成果”的统计口径不同。</span></p>}
      <div className="sg-research-profile-stats"><span>关联论文 <strong>{p.total_papers}</strong> 篇</span><span>已有分类 <strong>{p.coverage[scheme] ?? 0}</strong> 篇</span><span>论文年份 {p.start_year ?? '未知'}—{p.end_year ?? '未知'}</span></div>
      <p className="sg-research-profile-notice"><Information size={16} aria-hidden="true" /><span>分类结果表征论文研究内容，不作为正式学科归属的认定依据。</span></p>
      {rows.length === 0 && <div className="sg-research-profile-empty"><strong>暂时还不能展示研究方向</strong><p>已找到 {p.total_papers} 篇关联论文，但当前分类口径下尚无带来源依据的可展示分类。这不表示学者没有研究方向。</p><details><summary>查看这些论文</summary><ul>{p.papers.map((paper) => <li key={paper.publication_id}><Link to={`/outputs/${paper.publication_id}`}>{paper.title}</Link></li>)}</ul></details></div>}
      {(all ? rows : rows.slice(0, 10)).map((row) => <details className="sg-research-profile-direction" key={`${row.scheme_version}:${row.code}`}>
        <summary>{row.name}（{row.code}） · {row.paper_count} 篇{scheme === 'NSFC_APPLICATION_CODE' ? `，其中主方向 ${row.primary_paper_count} 篇` : ''}</summary>
        <p>标准版本：{row.scheme_version}；来源：{row.source_kinds.map((s) => sources[s] ?? s).join('、')}</p>
        <ul>{row.publication_ids.map((id) => { const paper = p.papers.find((v) => v.publication_id === id); return <li key={id}><Link to={`/outputs/${id}`}>{paper?.title ?? id}</Link>（{paper?.year ?? '年份未知'}）</li>; })}</ul>
      </details>)}
      {rows.length > 10 && <button type="button" onClick={() => setAll(!all)}>{all ? '收起' : `查看全部 ${rows.length} 个方向`}</button>}
      <p className="sg-research-profile-help"><Information size={16} aria-hidden="true" /><span>研究方向根据论文内容智能生成，仅供参考，也不代表学者的正式学科归属或项目申报方向。每篇论文可涉及多个方向，因此各方向的论文篇数不能直接相加。</span></p>
    </>}
  </section>;
}
