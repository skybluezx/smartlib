import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { DataAssetTrace, GovernanceDashboard as GovernanceDashboardData } from '../../generated/smartlib-api';
import { GovernanceDashboard } from './GovernanceDashboard';

const dashboard: GovernanceDashboardData = {
  summary: {
    visible_assets: 4,
    registered_sources: 4,
    license_grants: 4,
    effective_license_grants: 3,
    licenses_requiring_review: 1,
    open_quality_issues: 1,
    human_confirmation_issues: 1,
    active_contracts: 1,
    synthetic_assets: 4,
    generated_at: '2026-08-26T00:00:00Z',
  },
  licenses: [{
    license_grant_id: '78000000-0000-4000-8000-000000000002',
    data_asset_id: '73000000-0000-4000-8000-000000000002',
    asset_name: '中文学术期刊数据库',
    source_name: '中文学术期刊数据库',
    allowed_content: ['元数据'],
    allowed_purposes: ['检索'],
    prohibited_purposes: ['模型训练'],
    valid_from: '2026-01-01T00:00:00Z',
    valid_to: '2026-10-15T23:59:59Z',
    authorization_state: 'pending',
    effective_state: 'review_required',
    decision: 'deny',
    synthetic: true,
  }],
  quality_issues: [{
    quality_issue_id: '7b000000-0000-4000-8000-000000000003',
    data_asset_id: '73000000-0000-4000-8000-000000000002',
    asset_name: '中文学术期刊数据库',
    title: '许可用途等待人工复核',
    description: '许可未明确',
    severity: 'critical',
    issue_state: 'open',
    requires_human_confirmation: true,
    quality_rule_code: 'license_purpose_authorized',
    quality_rule_name: '许可用途明确性',
    run_state: 'failed',
    observed_value: 0,
    expected_value: 1,
    responsibility: 'license_reviewer',
    detected_at: '2026-08-26T00:30:00Z',
  }],
  audit_events: [],
};

const trace: DataAssetTrace = {
  data_asset_id: '73000000-0000-4000-8000-000000000002',
  asset_name: '中文学术期刊数据库',
  asset_type: 'licensed_resource',
  lifecycle_state: 'active',
  synthetic: true,
  dataset_version: 'governance-demo-v1',
  domain_name: '图书馆知识资源治理域',
  source_system_id: '72000000-0000-4000-8000-000000000002',
  source_name: '中文学术期刊数据库',
  source_owner_department: '图书馆资源建设部',
  source_authorization_state: 'pending',
  latest_asset_version: 1,
  latest_schema_version: 'governance-demo-v1',
  contract_codes: [],
  steward_responsibilities: ['license_reviewer'],
};

vi.mock('../../shared/api/smartlib', () => ({
  getGovernanceDashboardView: vi.fn(() => Promise.resolve(dashboard)),
  getGovernanceAssetTrace: vi.fn(() => Promise.resolve(trace)),
}));

describe('GovernanceDashboard', () => {
  it('renders API facts, default deny, and traceable source information', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><GovernanceDashboard /></QueryClientProvider>);

    expect(await screen.findByText('当前为版本化模拟治理数据')).toBeInTheDocument();
    expect(screen.getByText('待复核')).toBeInTheDocument();
    expect(screen.getByText('1 项不可直接放行')).toBeInTheDocument();
    expect(screen.getByText('2026年10月15日')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '追溯' }));
    expect(await screen.findByText('图书馆资源建设部')).toBeInTheDocument();
    expect(screen.getAllByText('governance-demo-v1')).toHaveLength(2);
  });
});
