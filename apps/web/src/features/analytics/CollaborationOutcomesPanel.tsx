import { useState } from 'react';
import {
  Accordion, AccordionItem, Dropdown, InlineNotification, Pagination,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@carbon/react';
import { Link } from 'react-router-dom';
import type { CollaborationOutcomes } from '../../generated/smartlib-api';

const number = (value?: number | null) => value == null ? '未覆盖' : value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });

export function CollaborationOutcomesPanel({ data }: { data: CollaborationOutcomes }) {
  const [mode, setMode] = useState('全部署名结构');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const papers = data.papers.filter((p) => mode === '全部署名结构' || p.mode === mode);
  const currentPage = Math.min(page, Math.max(1, Math.ceil(papers.length / pageSize)));
  return <section className="sg-outcomes">
    <header><h2>合作方式与成果表现</h2><p>比较同一论文范围内的署名机构构成、被引表现与发表载体；可在上方限定年份、机构和项目种类。</p></header>
    <InlineNotification kind="info" title="描述性比较，不作因果判断" subtitle="代表性论著不是全校完整样本。机构、作者或指标不完整会单独标明；当前不据此给团队排名或估算项目获批概率。" hideCloseButton />
    <p className="sg-outcomes-vintage">{data.metric_release_id ? `InCites 数据截至 ${data.metric_indexed_through ?? '未标明'} · 版本 ${data.metric_release_id}` : '当前身份没有可用的已验证 InCites 指标版本，相关指标保留缺失。'}</p>
    <div className="sg-outcomes-table" tabIndex={0} role="region" aria-label="合作方式与成果表现比较，可横向滚动">
      <Table size="lg"><TableHead><TableRow>{['署名结构', '论文数', 'CNCI 中位数', 'CNCI 均值', 'CNCI 覆盖', '被引中位数 / 覆盖', '同年 JIF 中位数 / 覆盖'].map((h) => <TableHeader key={h}>{h}</TableHeader>)}</TableRow></TableHead>
        <TableBody>{data.groups.map((g) => <TableRow key={g.mode}>
          <TableCell>{g.mode}</TableCell><TableCell>{g.publication_count}</TableCell>
          <TableCell>{number(g.cnci_median)}</TableCell><TableCell>{number(g.cnci_mean)}</TableCell>
          <TableCell>{g.cnci_covered} / {g.publication_count}</TableCell>
          <TableCell>{number(g.citations_median)} / {g.cited_covered} 篇</TableCell>
          <TableCell>{number(g.jif_median)} / {g.jcr_covered} 篇</TableCell>
        </TableRow>)}</TableBody></Table>
    </div>
    <Accordion><AccordionItem title="统计口径与解释边界">{data.notes.map((note) => <p key={note}>{note}</p>)}<p>版本：<code>{data.definition_version}</code>；论文范围指纹：<code>{data.scope_hash}</code>。JIF 是期刊指标，不等于单篇论文质量。</p></AccordionItem></Accordion>
    <div className="sg-outcomes-evidence-heading"><h3>逐篇依据</h3><Dropdown id="outcome-mode" titleText="查看署名结构" label="全部署名结构" items={['全部署名结构', ...data.groups.map((g) => g.mode)]} selectedItem={mode} onChange={({ selectedItem }) => { setMode(selectedItem ?? '全部署名结构'); setPage(1); }} /></div>
    {papers.length === 0 ? <p>该组暂无论文，请选择其他署名结构或调整上方分析范围。</p> : <>
      <div className="sg-outcomes-table" tabIndex={0} role="region" aria-label="论文依据，可横向滚动"><Table><TableHead><TableRow>{['论文 / 年份', '署名结构', '署名机构（按登记层次归并）', '机构覆盖作者 / 作者数', 'CNCI', '被引次数'].map((h) => <TableHeader key={h}>{h}</TableHeader>)}</TableRow></TableHead><TableBody>
        {papers.slice((currentPage - 1) * pageSize, currentPage * pageSize).map((p) => <TableRow key={p.publication_id}>
          <TableCell><Link to={`/outputs/${p.publication_id}`}>{p.title}</Link><br /><code>{p.publication_year ?? '年份未收录'}</code></TableCell>
          <TableCell>{p.mode}</TableCell><TableCell>{p.institution_names.join('；') || '尚无可用机构'}</TableCell>
          <TableCell>{p.affiliation_author_count} / {p.author_count}</TableCell><TableCell>{number(p.cnci)}</TableCell><TableCell>{number(p.times_cited)}</TableCell>
        </TableRow>)}
      </TableBody></Table></div>
      <Pagination page={currentPage} pageSize={pageSize} pageSizes={[10, 20, 50]} totalItems={papers.length} itemsPerPageText="每页论文数" backwardText="上一页" forwardText="下一页" onChange={({ page: next, pageSize: size }) => { setPage(next); setPageSize(size); }} />
    </>}
  </section>;
}
