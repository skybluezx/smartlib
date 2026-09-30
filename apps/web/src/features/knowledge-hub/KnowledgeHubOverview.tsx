import { Notice as InlineNotification } from '../../shared/components/Notice';
import { useQuery } from '@tanstack/react-query';
import {
  CheckmarkFilled,
  DataBase,
  Document,
  IbmKnowledgeCatalog,
  Renew,
  Search,
  UserMultiple,
  WarningAlt,
} from '@carbon/icons-react';
import { Button, InlineLoading,  ProgressBar } from '@carbon/react';
import { Link } from 'react-router-dom';
import { labels } from './hubCatalog';
import { getKnowledgeHubOverviewView } from '../../shared/api/smartlib';

const entityLabels: Record<string, string> = {
  person: '学者', publication: '论文', organization: '机构', funding_program: '资助计划', project: '项目',
};

const layerLabels: Record<string, string> = {
  identity: '论文身份', attribution: '成果归属', enrichment: '元数据丰富化',
};

const verificationStateLabels: Record<string, string> = {
  pending: '待处理', normalized: '等待自动核验', manual_review: '待人工核验',
  auto_verified: '自动确认', human_verified: '人工确认', corrected: '修正后确认',
  reverification_required: '待重新核验', verification_conflict: '核验冲突',
  rejected: '已驳回', superseded: '已替代',
};

function PageHeader() {
  return <header className="kh-page-header"><div><p>知识基础设施 / 运行态势</p><h1>工作总览</h1><span>汇集各应用的数据接入、治理任务、资源与服务运行情况</span></div><div className="kh-header-actions"><Link className="cds--btn cds--btn--secondary" to="/knowledge-hub/imports">导入论文</Link><Link className="cds--btn cds--btn--primary" to="/knowledge-hub/verifications/publications">进入论文核验</Link></div></header>;
}

export function KnowledgeHubOverview() {
  const overview = useQuery({ queryKey: ['knowledge-hub-overview'], queryFn: getKnowledgeHubOverviewView });
  if (overview.isPending) return <><PageHeader /><div className="kh-overview-skeleton"><span /><span /><span /><span /><span /></div></>;
  if (overview.isError) return <><PageHeader /><InlineNotification kind="error" title="总览加载失败" subtitle={overview.error.message} actions={<Button kind="ghost" onClick={() => void overview.refetch()}>重试</Button>} /></>;

  const data = overview.data;
  const latest = data.latest_import;
  const completion = latest?.total_items ? Math.round(latest.completed_items / latest.total_items * 100) : 0;
  return <div className="kh-page">
    <PageHeader />
    <section className="kh-workflow-links" aria-label="馆员常用工作">
      <Link to="/knowledge-hub/sources"><strong>接入数据</strong><span>登记来源，导入论文与馆务数据</span></Link>
      <Link to="/knowledge-hub/governance"><strong>治理与核验</strong><span>检查质量，核验记录，审核变更</span></Link>
      <Link to="/knowledge-hub/resources"><strong>维护资源</strong><span>资产、许可、元数据和期刊指标</span></Link>
      <Link to="/knowledge-hub/analysis"><strong>分析与服务</strong><span>查看科研分析和馆务月度趋势</span></Link>
    </section>
    <section className="kh-metrics" aria-label="核心数据规模">
      {Object.entries(entityLabels).map(([key, label]) => <article key={key}>
        <span>{label}</span><strong>{data.entity_counts[key] ?? 0}</strong><small>PostgreSQL 权威对象</small>
      </article>)}
      <article><span>数据来源</span><strong>{data.registered_sources}</strong><small>已登记来源系统</small></article>
      <article className="attention"><span>待完成核验</span><strong>{data.pending_verifications}</strong><small>来源记录 · {data.conflict_fields} 个冲突字段</small></article>
    </section>

    <div className="kh-overview-grid">
      <section className="kh-section kh-import-status">
        <div className="kh-section-heading"><div><h2>最近导入批次</h2><p>受控导入不会随 API 启动重复执行</p></div><Document size={20} /></div>
        {latest ? <>
          <dl><div><dt>数据版本</dt><dd>{latest.dataset_version}</dd></div><div><dt>批次状态</dt><dd>{labels[latest.batch_state] ?? latest.batch_state}</dd></div><div><dt>总记录</dt><dd>{latest.total_items}</dd></div><div><dt>待人工</dt><dd>{latest.manual_review_items}</dd></div></dl>
          <ProgressBar label="已完成核验的来源记录" helperText={`${latest.completed_items} / ${latest.total_items}`} value={completion} />
        </> : <div className="kh-empty"><Document size={24} /><p>尚无可见导入批次</p></div>}
      </section>

      <section className="kh-section">
        <div className="kh-section-heading"><div><h2>存储与投影服务</h2><p>运行状态与当前业务读取后端分开标识</p></div><DataBase size={20} /></div>
        <div className="kh-service-list">{data.services.map((service) => <article key={service.service}>
          {service.state === 'available' ? <CheckmarkFilled size={16} /> : <WarningAlt size={16} />}
          <div><strong>{service.service}</strong><span>{service.purpose}</span></div>
          <div className="kh-service-state"><b>{service.state === 'available' ? '可用' : '不可用'}</b><small>{service.active_backend ? '当前读取后端' : service.detail}</small></div>
        </article>)}</div>
      </section>

      <section className="kh-section kh-queue-summary">
        <div className="kh-section-heading"><div><h2>核验工作量</h2><p>当前全部论文来源记录的有效状态分布</p></div><IbmKnowledgeCatalog size={20} /></div>
        <div className="kh-state-list">{Object.entries(data.verification_states).map(([state, count]) => <div key={state}><span>{verificationStateLabels[state] ?? state}</span><strong>{count}</strong></div>)}</div>
        <div className="kh-layer-overview">{Object.entries(data.verification_layers ?? {}).map(([layer, statuses]) => <article key={layer}><header><strong>{layerLabels[layer] ?? layer}</strong><small>{layer === 'enrichment' ? '非阻塞' : '阻塞核验'}</small></header><div>{!Object.keys(statuses).length&&<span>暂无分层统计</span>}{Object.entries(statuses).map(([status, count]) => <span key={status}><em>{status}</em><b>{count}</b></span>)}</div></article>)}</div>
      </section>

      <section className="kh-section kh-supply-summary">
        <div className="kh-section-heading"><div><h2>供应链状态</h2><p>权威库写入后通过事务事件更新派生存储</p></div><Renew size={20} /></div>
        <div className="kh-flow-line"><span><UserMultiple size={18} />PostgreSQL</span><i /><span><Search size={18} />OpenSearch</span><i /><span><IbmKnowledgeCatalog size={18} />HugeGraph</span></div>
        {data.unpublished_events ? <InlineLoading status="active" description={`${data.unpublished_events} 个事件等待投影`} /> : <InlineLoading status="finished" description="当前没有待派发事件；数据完整一致性需另行对账" />}
      </section>
    </div>
    <p className="kh-generated">统计生成时间：{new Date(data.generated_at).toLocaleString('zh-CN')}</p>
  </div>;
}
