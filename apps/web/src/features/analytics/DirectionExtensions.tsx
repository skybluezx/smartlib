import { runtimeConfig } from '../../shared/config/runtime';
import { useWorkbenchPreference } from './workbenchSettings';
import '../catalog/ResearchAnalysis.css';
import { DirectionYearChart } from './DirectionYearChart';
import { useQuery } from '@tanstack/react-query';
import { ComboBox, InlineNotification } from '@carbon/react';
import { Information } from '@carbon/icons-react';
import { Link } from 'react-router-dom';
import type { DisciplineWorkspace, DirectionScheme } from '../../generated/smartlib-api';
import { api } from '../../shared/api/research';
import { getScopedResearchAnalysis } from '../../generated/smartlib-api';

export function DirectionExtensions({ workspace, scheme, dataVersion }: { workspace: DisciplineWorkspace; scheme: DirectionScheme; dataVersion?: string | null | undefined }) {
  const [institution, setInstitution] = useWorkbenchPreference<{ id: string; name: string; kind: string } | null>('direction.institution', null);
  const choices = useQuery({ queryKey: ['research-entities'], queryFn: () => api<{ id: string; name: string; kind: string }[]>('/entities') });
  const ids = workspace.papers.map(p => p.object_id).sort();
  const result = useQuery({
    queryKey: ['scoped-direction-extensions', dataVersion, ids, scheme.scheme, scheme.version, institution?.id],
    queryFn: async ({signal}) => { const response = await getScopedResearchAnalysis({baseUrl: new URL(runtimeConfig.apiBaseUrl || '/', window.location.origin).href.replace(/\/$/, ''), signal, body: {publication_ids: ids, scheme: scheme.scheme, scheme_version: scheme.version, collaboration_institution_id: institution?.id ?? null}}); if (response.error) throw new Error('合作线索加载失败'); return response.data; },
  });
  const papers = new Map(workspace.papers.map(p => [p.object_id, p]));
  const links = (paperIds: string[]) => <ul>{paperIds.map(id => <li key={id}><Link to={`/outputs/${id}`}>{papers.get(id)?.title ?? id}</Link></li>)}</ul>;
  return <div className="sg-research-analysis sg-direction-extensions">
    <section className="sg-output-section"><h2>年度变化</h2>
      <p><Information size={16} /> 按当前分析范围、分类体系及论文发表年份统计；年份缺失单独列示，未显示的年份不代表零产出。</p>
      <DirectionYearChart workspace={workspace} scheme={scheme} />
    </section>
    <section className="sg-output-section"><h2>潜在合作线索</h2>
      <div className="sg-research-collaboration-filter"><ComboBox id="direction-collaboration-institution" titleText="限定机构" placeholder="全部机构，可输入名称检索"
        items={choices.data?.filter(x => x.kind === 'organization') ?? []} selectedItem={institution} itemToString={x => x?.name ?? ''}
        onChange={({selectedItem}) => setInstitution(selectedItem ?? null)} shouldFilterItem={({item,inputValue}) => item.name.toLowerCase().includes((inputValue ?? '').toLowerCase())} /></div>
      <p><Information size={16} /> 候选双方均须属于所选机构及下级机构（按范围内作者署名识别）。每人至少两篇论文、至少两个共同方向，且本范围未见共同署名。展示前30对，不认定现实合作关系。</p>
      {choices.isError && <InlineNotification kind="warning" title="机构选项加载失败" hideCloseButton />}
      <div className="sg-research-scroll" role="region" aria-label="潜在合作线索列表" tabIndex={0}>
        {result.isPending ? <p role="status">正在分析合作线索…</p> : result.isError ? <InlineNotification kind="error" title="合作线索加载失败" subtitle={result.error.message} hideCloseButton /> : <>
          {result.data.collaboration.map(r => <details key={`${r.a}:${r.b}`}><summary>{r.a_name} — {r.b_name}：{r.shared.map(s => s.name).join('、')}</summary><p>{r.note}</p><Link to={`/scholars/${r.a}`}>{r.a_name}的画像</Link>{links(r.a_papers)}<Link to={`/scholars/${r.b}`}>{r.b_name}的画像</Link>{links(r.b_papers)}</details>)}
          {!result.data.collaboration.length && <p>当前范围没有满足规则的候选；不等于没有合作机会。</p>}
        </>}
      </div>
    </section>
  </div>;
}
