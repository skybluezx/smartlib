import { useQuery } from '@tanstack/react-query';
import type { Icon } from '@phosphor-icons/react';
import {
  ArrowsClockwiseIcon as ArrowsClockwise,
  BooksIcon as Books,
  CheckCircleIcon as CheckCircle,
  DatabaseIcon as Database,
  InfoIcon as Info,
  LinkSimpleIcon as LinkSimple,
  ShieldCheckIcon as ShieldCheck,
  UserCircleIcon as UserCircle,
  WarningCircleIcon as WarningCircle,
} from '@phosphor-icons/react';
import { useState, type ReactNode } from 'react';
import type { GovernanceAuditEventView, LicenseGrantView } from '../../generated/smartlib-api';
import { getGovernanceAssetTrace, getGovernanceDashboardView } from '../../shared/api/smartlib';

function SectionHeader({ title, text, action }: { title: string; text?: string; action?: ReactNode }) {
  return <div className="section-header"><div><h2>{title}</h2>{text && <p>{text}</p>}</div>{action}</div>;
}

function MetricCard({ icon: IconComponent, label, value, delta, color }: {
  icon: Icon; label: string; value: string; delta: string; color: string;
}) {
  return <article className={`metric-card ${color}`}><div className="metric-icon"><IconComponent size={22} weight="duotone" /></div><span>{label}</span><strong>{value}</strong><small>{delta}</small></article>;
}

function licenseStateLabel(item: LicenseGrantView): string {
  if (item.effective_state === 'effective') return '有效';
  if (item.effective_state === 'expired') return '已到期';
  if (item.effective_state === 'not_yet_valid') return '未生效';
  if (item.effective_state === 'review_required') return '待复核';
  return '已拒绝';
}

function dateLabel(value: string | null): string {
  if (!value) return '长期';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(value));
}

function auditLabel(item: GovernanceAuditEventView): string {
  const labels: Record<string, string> = {
    'governance.asset.seeded': '版本化模拟治理资产已登记',
    'license.purpose.denied': '未明确许可的处理请求已拒绝',
    'quality.issue.opened': '数据质量问题已进入处理闭环',
    'governance.dashboard.read': '治理工作台已按当前身份读取',
    'governance.asset.trace.read': '数据资产来源链路已追溯',
  };
  return labels[item.action] ?? item.action;
}

export function GovernanceDashboard() {
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
  const dashboard = useQuery({ queryKey: ['governance-dashboard'], queryFn: getGovernanceDashboardView });
  const trace = useQuery({
    queryKey: ['governance-asset-trace', selectedAssetId],
    queryFn: () => {
      if (selectedAssetId === null) throw new Error('未选择治理资产');
      return getGovernanceAssetTrace(selectedAssetId);
    },
    enabled: selectedAssetId !== null,
  });

  if (dashboard.isPending) return <section className="panel governance-live-state" aria-live="polite"><ArrowsClockwise className="spin" size={22} /><div><strong>正在读取权威治理库</strong><p>Web → FastAPI → PostgreSQL 18 → RLS；页面不使用固定治理数字。</p></div></section>;
  if (dashboard.isError) return <section className="panel governance-live-state error" role="alert"><WarningCircle size={22} /><div><strong>治理服务暂不可用</strong><p>{dashboard.error.message}</p></div></section>;

  const data = dashboard.data;
  return <div className="page-stack">
    <section className="panel synthetic-governance-note"><Info size={20} /><div><strong>当前为版本化模拟治理数据</strong><p>所有数字由真实数据库事实按当前身份计算；这些记录不代表学校已采购、接入或授权相应资源。</p></div><span>governance-demo-v1</span></section>
    <div className="metric-grid four">
      <MetricCard icon={Books} label="资源许可台账" value={String(data.summary.license_grants)} delta={`${data.summary.licenses_requiring_review} 项不可直接放行`} color="orange" />
      <MetricCard icon={Database} label="当前可见数据资产" value={String(data.summary.visible_assets)} delta={`${data.summary.registered_sources} 个已登记来源`} color="teal" />
      <MetricCard icon={ShieldCheck} label="当前有效许可" value={String(data.summary.effective_license_grants)} delta="仅批准且在有效期内" color="purple" />
      <MetricCard icon={ArrowsClockwise} label="待处理质量问题" value={String(data.summary.open_quality_issues)} delta={`${data.summary.human_confirmation_issues} 项需人工确认`} color="blue" />
    </div>
    <section className="panel governance-table">
      <SectionHeader title="电子资源许可矩阵" text="可访问不等于可任意处理；未知、待复核或到期许可默认拒绝。" action={<span className="api-source-badge"><CheckCircle size={15} /> 权威 API</span>} />
      <div className="discipline-table-wrap"><table><thead><tr><th>资源</th><th>可用内容</th><th>允许用途</th><th>有效期</th><th>决策</th><th>来源</th></tr></thead><tbody>{data.licenses.map((item) => <tr key={item.license_grant_id}><td><strong>{item.asset_name}</strong>{item.synthetic && <small className="synthetic-cell">模拟</small>}</td><td>{item.allowed_content.join('、') || '未明确'}</td><td>{item.allowed_purposes.join('、') || '未明确'}</td><td>{dateLabel(item.valid_to)}</td><td><span className={`status-badge ${item.decision === 'allow' ? 'active' : 'pending'}`}>{licenseStateLabel(item)}</span></td><td><button className="text-button" onClick={() => setSelectedAssetId(item.data_asset_id)}><LinkSimple size={15} /> 追溯</button></td></tr>)}</tbody></table></div>
    </section>
    {selectedAssetId && <section className="panel governance-trace" aria-live="polite">
      <SectionHeader title="资产来源与责任链" text="从当前可见资产反查治理域、来源授权、版本、契约和责任。" />
      {trace.isPending ? <p>正在核验来源链路…</p> : trace.isError ? <p className="error">{trace.error.message}</p> : <div className="trace-grid">
        <span><small>资产</small><strong>{trace.data.asset_name}</strong></span><span><small>治理域</small><strong>{trace.data.domain_name}</strong></span><span><small>来源系统</small><strong>{trace.data.source_name}</strong></span><span><small>责任部门</small><strong>{trace.data.source_owner_department}</strong></span><span><small>数据版本</small><strong>{trace.data.dataset_version ?? trace.data.latest_schema_version ?? '待登记'}</strong></span><span><small>契约 / 责任</small><strong>{[...trace.data.contract_codes, ...trace.data.steward_responsibilities].join('、') || '待登记'}</strong></span>
      </div>}
    </section>}
    <div className="two-column governance-bottom">
      <section className="panel"><SectionHeader title="数据质量处理闭环" text="问题不静默改写源事实，需明确规则、运行状态与人工责任。" /><div className="audit-list">{data.quality_issues.map((issue) => <span key={issue.quality_issue_id}><WarningCircle size={17} /><strong>{issue.title}</strong><small>{issue.asset_name} / {issue.quality_rule_name ?? '待登记规则'} / {issue.run_state ?? '未运行'} / {issue.responsibility ?? '待分配责任'} / {issue.requires_human_confirmation ? '需人工确认' : '规则处理'}</small></span>)}</div></section>
      <section className="panel audit-panel"><SectionHeader title="当前身份最近审计记录" /><div className="audit-list">{data.audit_events.length === 0 ? <span><Info size={17} />暂无当前身份可见记录</span> : data.audit_events.map((item) => <span key={item.event_id}>{item.decision === 'denied' ? <ShieldCheck size={17} /> : <UserCircle size={17} />}<strong>{auditLabel(item)}</strong><small>{new Date(item.occurred_at).toLocaleString('zh-CN')} / {item.decision}</small></span>)}</div></section>
    </div>
  </div>;
}
