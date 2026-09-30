import { Information } from '@carbon/icons-react';
import type { KnowledgeObjectDetailView } from '../../generated/smartlib-api';
import './publicationJournalMetrics.css';

export function PublicationJournalMetrics({ detail }: { detail: KnowledgeObjectDetailView }) {
  const records = detail.journal_metrics ?? [];
  const rawYear = detail.type_details?.publication_year ?? detail.object.publication_year;
  const year = typeof rawYear === 'number' || typeof rawYear === 'string' ? rawYear : null;
  return <section className="sg-output-section sg-publication-journal-metrics" aria-label="论文发表年期刊指标">
    <header><h2>论文发表年期刊指标</h2><p className="sg-journal-detail-note"><Information size={18} aria-hidden="true" /><span>期刊指标按论文发表年份匹配，缺少同年数据时不使用其他年份替代。指标反映期刊层面表现，不代表单篇论文质量。</span></p></header>
    {records.length ? <div className="sg-journal-detail-scroll" role="region" aria-label="期刊指标明细，可横向滚动" tabIndex={0}>
      <table><thead><tr><th>指标体系 / 年份</th><th>影响因子</th><th>分区</th><th>适用学科</th><th>来源版本</th></tr></thead>
        <tbody>{records.map(record => <tr key={record.record_id}>
          <td>{record.metric_system === 'jcr' ? 'JCR' : record.metric_system === 'cas_partition' ? '中科院分区' : record.metric_system} · {record.metric_year}</td>
          <td>{record.impact_factor == null ? '—' : `${record.impact_factor_is_upper_bound ? '<' : ''}${record.impact_factor}`}</td>
          <td>{record.quartile == null ? '—' : record.metric_system === 'cas_partition' ? `${record.quartile.replace('Q', '')}区` : record.quartile}</td>
          <td>{record.categories?.length ? record.categories.join('；') : '未提供学科类别'}</td>
          <td>{record.release_label}<small>来源行 {record.source_row_number}</small></td>
        </tr>)}</tbody>
      </table>
    </div> : <p className="sg-journal-detail-empty">{year ? `尚未收录与论文发表年份（${year} 年）匹配的期刊指标。` : '论文发表年份尚未补全，暂无法匹配同年期刊指标。'}</p>}
    {records.length > 0 && <p className="sg-journal-detail-footnote">“—”表示该指标缺失。多学科或多来源记录分别展示，保留不同分区及数值，不合并为单一等级。</p>}
  </section>;
}
