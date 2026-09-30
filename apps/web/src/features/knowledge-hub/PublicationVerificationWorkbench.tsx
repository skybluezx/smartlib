import { Notice as InlineNotification } from '../../shared/components/Notice';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Checkmark,
  Close,
  DocumentView,
  Launch,
  Renew,
  Search as SearchIcon,
} from '@carbon/icons-react';
import {
  Button,
  
  Loading,
  Modal,
  Pagination,
  Search,
  Select,
  SelectItem,
  SkeletonText,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TextArea,
  TextInput,
} from '@carbon/react';
import { useState, type ReactNode } from 'react';
import { useOutletContext } from 'react-router-dom';
import type {
  FieldVerificationView,
  FulltextPreverificationView,
  PublicationFulltextResourceView,
  PublicationSupplementCreate,
  PublicationSupplementView,
  PublicationVerificationDetail,
  VerificationCheckView,
} from '../../generated/smartlib-api';
import {
  getPublicationVerificationPage,
  getPublicationFulltextsView,
  getPublicationSupplementsView,
  getPublicationVerificationView,
  decidePublicationSupplementView,
  submitPublicationSupplementView,
  submitPublicationVerification,
  uploadPublicationFulltextView,
} from '../../shared/api/smartlib';
import type { KnowledgeHubOutletContext } from './KnowledgeHubShell';

const stateLabels: Record<string, string> = {
  pending: '待处理', normalized: '等待自动核验', manual_review: '待人工核验',
  auto_verified: '自动确认', human_verified: '人工确认', corrected: '修正后确认',
  reverification_required: '待重新核验', verification_conflict: '核验冲突',
  rejected: '已驳回', superseded: '已替代',
};

const fieldLabels: Record<string, string> = {
  title: '题名', journal_name: '期刊', publication_year: '发表年份',
  doi: 'DOI', pmid: 'PMID', pmcid: 'PMCID',
};

const layerStatusLabels: Record<string, string> = {
  pending: '待运行', passed: '已通过', conflict: '存在冲突', incomplete: '待补齐',
  not_applicable: '不适用',
};

const reviewAreaLabels: Record<string, string> = {
  identity: '信息', attribution: '作者', enrichment: '补充',
};

const evidenceSourceLabels: Record<string, string> = {
  controlled_excel: 'Excel 原始记录', crossref: 'Crossref', ncbi_pubmed: 'NCBI PubMed',
  local_fulltext_preverification: '本地论文全文',
};

const preverificationStatusLabels: Record<string, string> = {
  ready: '可确认', review_required: '需要复核', conflict: '存在冲突',
  applied: '已写回', superseded: '已替代',
};

const preverificationCheckLabels: Record<string, string> = {
  passed: '通过', review_required: '待确认', conflict: '冲突', missing: '未发现',
};

const evidenceKeyLabels: Record<string, string> = {
  doi: 'DOI', pmid: 'PMID', pmcid: 'PMCID', title: '题名', journal: '期刊',
  issue: '期号', volume: '卷号', pages: '页码', article_number: '文章号',
  issn: 'ISSN', eissn: 'EISSN', name: '姓名', given: '名', family: '姓',
  order: '作者顺序', sequence: '作者角色', orcid: 'ORCID', affiliations: '作者单位',
  agency: '资助机构', country: '国家或地区', grant_id: '基金编号', award: '基金编号',
  pubmed: 'PubMed', crossref: 'Crossref', keywords: '关键词', mesh_terms: 'MeSH 主题词',
  licenses: '许可信息', fulltext_urls: '全文地址', publication_types: '论文类型',
  comments_corrections: '勘误或撤稿信息', crossref_updates: 'Crossref 更新',
  crossref_relations: 'Crossref 关联记录', content_version: '内容版本',
  delay_in_days: '延迟天数', URL: '地址', start: '生效时间', date_time: '日期时间',
  'date-time': '日期时间', 'date-parts': '日期', 'delay-in-days': '延迟天数',
  'content-version': '内容版本', 'award-info': '基金详情', 'award-number': '基金编号',
  'id-type': '标识类型', 'asserted-by': '提供方', 'doi-asserted-by': 'DOI 提供方',
};

const supplementKindLabels: Record<string, string> = {
  metadata: '出版信息', identifier: '标识符', fulltext: '全文文件',
  funding: '基金资助', lifecycle: '更正、撤稿等状态',
};

const supplementStatusLabels: Record<string, string> = {
  received: '已接收', auto_applied: '已自动写回', needs_review: '待人工确认',
  accepted: '已接受', rejected: '已拒绝',
};

const candidateFieldLabels: Record<string, string> = {
  title: '题名', journal_name: '期刊', publication_year: '发表年份',
  publication_date: '发表日期', volume: '卷号', issue: '期号', pages: '页码',
  article_number: '文章号', abstract: '摘要',
  'metadata.title': '题名', 'metadata.journal_name': '期刊',
  'metadata.publication_year': '发表年份', 'metadata.publication_date': '发表日期',
  'metadata.volume': '卷号', 'metadata.issue': '期号', 'metadata.pages': '页码',
  'metadata.article_number': '文章号', 'metadata.abstract': '摘要',
  'attributes.keywords': '关键词', 'attributes.mesh_terms': 'MeSH 主题词',
  'attributes.licenses': '许可信息', 'attributes.fulltext_urls': '全文地址',
  'attributes.publication_types': '论文类型', 'attributes.funders': '资助机构',
  'attributes.grants': '基金编号', 'identifiers.doi': 'DOI',
  'identifiers.pmid': 'PMID', 'identifiers.pmcid': 'PMCID',
  'relation.funded_by': '基金资助关系', 'fulltext.resource': '全文文件',
};

interface AuthorCandidate {
  order?: number | undefined;
  name?: string | undefined;
  given?: string | null | undefined;
  family?: string | null | undefined;
  orcid?: string | null | undefined;
  affiliations?: string[] | undefined;
}

interface DecisionSelection {
  choices: Record<string, 'source' | 'candidate'>;
  acceptedCheckCodes: string[];
  awardeeAuthorOrder: number | null;
  correspondingAuthorOrders: number[];
  coFirstAuthorOrders: number[];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未提供';
  return typeof value === 'string' ? value.replace(/<[^>]+>/g, '') : JSON.stringify(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readableKey(key: string) {
  return evidenceKeyLabels[key] ?? key.replaceAll('_', ' ');
}

function scalarEvidence(value: string | number | boolean): ReactNode {
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string' && /^https?:\/\//i.test(value)) return <a href={value} target="_blank" rel="noreferrer">打开链接 <Launch size={12} /></a>;
  return String(value).replace(/<[^>]+>/g, '');
}

function StructuredEvidence({ value, depth = 0 }: { value: unknown; depth?: number | undefined }): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="kh-no-evidence">未提供</span>;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return <span className="kh-evidence-text">{scalarEvidence(value)}</span>;
  if (Array.isArray(value)) {
    const items = value as unknown[];
    if (!items.length) return <span className="kh-no-evidence">未提供</span>;
    const scalarOnly = items.every((item) => ['string', 'number', 'boolean'].includes(typeof item));
    if (scalarOnly) return <ul className="kh-evidence-tags">{items.map((item, index) => <li key={index}>{scalarEvidence(item as string | number | boolean)}</li>)}</ul>;
    return <div className="kh-structured-list">{items.map((item, index) => <article key={index}><small>第 {index + 1} 项</small><StructuredEvidence value={item} depth={depth + 1} /></article>)}</div>;
  }
  if (isRecord(value)) {
    const entries = Object.entries(value).filter(([, item]) => item !== null && item !== undefined && item !== '');
    if (!entries.length) return <span className="kh-no-evidence">未提供</span>;
    return <dl className={`kh-structured-record depth-${Math.min(depth, 2)}`}>{entries.map(([key, item]) => <div key={key}><dt>{readableKey(key)}</dt><dd><StructuredEvidence value={item} depth={depth + 1} /></dd></div>)}</dl>;
  }
  return <span className="kh-no-evidence">暂不支持显示该类型</span>;
}

function FulltextPreverificationCard({ result }: { result: FulltextPreverificationView }) {
  return <section className={`kh-preverification is-${result.preverification_status}`}>
    <header><div><span>全文入库前核验</span><h3>{result.file_name}</h3></div><strong>{preverificationStatusLabels[result.preverification_status] ?? result.preverification_status}</strong></header>
    <div className="kh-preverification-metrics">
      <span><small>匹配置信度</small><strong>{Math.round(result.match_score * 100)}%</strong></span>
      <span><small>全文页数</small><strong>{result.page_count ?? '—'}</strong></span>
      <span><small>正文字符</small><strong>{result.text_length?.toLocaleString('zh-CN') ?? '—'}</strong></span>
      <span><small>解析方式</small><strong>{result.extraction_method === 'ocr' ? 'OCR' : '文字层'}</strong></span>
    </div>
    <div className="kh-preverification-checks">{result.checks.map((item) => <article key={item.code} className={`is-${item.status}`}>
      <header><strong>{item.label}</strong><span>{preverificationCheckLabels[item.status] ?? item.status}</span></header>
      <p>{item.reason}</p>
      {(item.source_value !== null || item.fulltext_value !== null) && <details><summary>查看来源与全文证据</summary><div><small>原记录</small><StructuredEvidence value={item.source_value} /><small>全文结果</small><StructuredEvidence value={item.fulltext_value} /></div></details>}
    </article>)}</div>
    <footer><span>建议标识符：DOI {result.proposed_identifiers.doi ?? '未发现'} · PMID {result.proposed_identifiers.pmid ?? '未发现'} · PMCID {result.proposed_identifiers.pmcid ?? '未发现'}</span>{result.shared_source_rows.length > 1 && <span>同一全文关联来源行：{result.shared_source_rows.join('、')}</span>}<details><summary>查看原文件位置与规则</summary><p>{result.source_path}</p><code>{result.rule_version} · SHA-256 {result.content_checksum}</code></details></footer>
  </section>;
}

function EvidenceValue({ value }: { value: unknown }) {
  const structured = Array.isArray(value) || isRecord(value);
  return <div className="kh-readable-evidence"><StructuredEvidence value={value} />{structured && <details className="kh-raw-json"><summary>查看原始 JSON</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>}</div>;
}

function authorCandidates(detail: PublicationVerificationDetail): AuthorCandidate[] {
  const check = (detail.layers ?? [])
    .find((layer) => layer.layer_code === 'attribution')?.checks
    .find((item) => item.check_code === 'awardee_author_match');
  const value = check?.authoritative_value;
  if (!value || typeof value !== 'object' || !('candidates' in value)) return [];
  const candidates = (value as { candidates?: unknown }).candidates;
  return Array.isArray(candidates) ? candidates as AuthorCandidate[] : [];
}

function WorkbenchHeader() {
  return <header className="kh-page-header"><div><p>数据核验 / 论文</p><h1>论文核验工作台</h1><span>逐字段比较原始著录与 Crossref、PubMed 权威证据，并形成可审计决定</span></div></header>;
}

function checkStatusLabel(check: VerificationCheckView, accepted: boolean) {
  if (accepted || check.check_status === 'passed') return '通过';
  if (check.check_status === 'conflict') return '冲突';
  if (check.check_status === 'missing') return '缺失';
  if (check.check_status === 'pending') return '待确认';
  return '不适用';
}

function FieldComparison({ field, check, choice, setChoice, editable, accepted, toggleAccepted }: {
  field: FieldVerificationView;
  check?: VerificationCheckView | undefined;
  choice: 'source' | 'candidate';
  setChoice: (choice: 'source' | 'candidate') => void;
  editable: boolean;
  accepted: boolean;
  toggleAccepted: () => void;
}) {
  const differs = JSON.stringify(field.source_value) !== JSON.stringify(field.candidate_value);
  const unresolved = check && ['conflict', 'missing', 'pending'].includes(check.check_status);
  return <article className={`kh-field-compare ${differs ? 'has-difference' : ''}`}>
    <header><div><strong>{fieldLabels[field.field_name] ?? field.field_name}</strong><span>{field.verification_status === 'conflict' ? '原始值与权威来源存在差异' : '原始值与权威来源一致'}</span></div><div className="kh-field-status">{field.match_score !== null && <b>{Math.round(field.match_score * 100)}%</b>}{check && <span className={`is-${accepted ? 'passed' : check.check_status}`}>{checkStatusLabel(check, accepted)}</span>}</div></header>
    <div className="kh-field-options">
      <label className={choice === 'source' ? 'selected' : ''}>
        <input type="radio" name={`${field.field_name}-choice`} checked={choice === 'source'} disabled={!editable} onChange={() => setChoice('source')} />
        <span>原始导入值</span><strong>{displayValue(field.source_value)}</strong>
      </label>
      <label className={choice === 'candidate' ? 'selected' : ''}>
        <input type="radio" name={`${field.field_name}-choice`} checked={choice === 'candidate'} disabled={!editable || field.candidate_value === null} onChange={() => setChoice('candidate')} />
        <span>{field.candidate_source_code === 'ncbi_pubmed' ? 'PubMed 候选值' : 'Crossref 候选值'}</span><strong>{displayValue(field.candidate_value)}</strong>
      </label>
    </div>
    <footer><span>{field.decision_reason ?? '暂无自动判定说明'}</span>{editable && unresolved && check.severity === 'blocking' && <label className="kh-inline-accept"><input type="checkbox" checked={accepted} onChange={toggleAccepted} />人工核对后接受</label>}{field.source_url && <a href={field.source_url} target="_blank" rel="noreferrer">打开来源 <Launch size={14} /></a>}</footer>
  </article>;
}

function MissingIdentifierField({ fieldName, sourceValue, check }: {
  fieldName: 'doi' | 'pmid' | 'pmcid';
  sourceValue: unknown;
  check?: VerificationCheckView | undefined;
}) {
  const candidateValue = check?.authoritative_value;
  const hasAnyValue = ![sourceValue, candidateValue].every((value) => value === null || value === undefined || value === '');
  return <article className="kh-field-compare kh-missing-identifier">
    <header><div><strong>{fieldLabels[fieldName]}</strong><span>{hasAnyValue ? '当前仅有核验证据，尚未生成可选择的独立字段记录' : '原始记录和权威来源均未提供该标识符'}</span></div><div className="kh-field-status"><span className="is-missing">未提供</span></div></header>
    <div className="kh-field-options kh-evidence-options">
      <div className="kh-evidence-value"><span>原始导入值</span><strong>{displayValue(sourceValue)}</strong></div>
      <div className="kh-evidence-value"><span>{fieldName === 'doi' ? 'Crossref 候选值' : 'PubMed 候选值'}</span><strong>{displayValue(candidateValue)}</strong></div>
    </div>
  </article>;
}

function EvidenceChecks({ checks, editable, accepted, toggleAccepted, sourceUrls, allowAccept = false }: {
  checks: VerificationCheckView[];
  editable: boolean;
  accepted: Set<string>;
  toggleAccepted: (code: string) => void;
  sourceUrls: Record<string, string | undefined>;
  allowAccept?: boolean | undefined;
}) {
  if (!checks.length) return null;
  return <div className="kh-field-list">{checks.map((item) => {
      const manuallyAccepted = accepted.has(item.check_code);
      const unresolved = ['conflict', 'missing', 'pending'].includes(item.check_status);
      const status = manuallyAccepted ? 'passed' : item.check_status;
      return <article key={item.check_code} className={`kh-field-compare kh-check-compare is-${status}`}>
        <header><div><strong>{item.check_label}</strong><span>系统交叉核验</span></div><div className="kh-field-status"><span className={`is-${status}`}>{checkStatusLabel(item, manuallyAccepted)}</span></div></header>
        <div className="kh-field-options kh-evidence-options">
          <div className="kh-evidence-value"><span>来源记录</span><EvidenceValue value={item.source_value} /></div>
          <div className={`kh-evidence-value ${status === 'passed' ? 'selected' : ''}`}><span>权威检索结果</span><EvidenceValue value={item.authoritative_value} /></div>
        </div>
        <footer><span className="kh-check-sources">证据来源：{item.evidence_sources.length ? item.evidence_sources.map((source, index) => <span key={source}>{index > 0 && '、'}{sourceUrls[source] ? <a href={sourceUrls[source]} target="_blank" rel="noreferrer">{evidenceSourceLabels[source] ?? source} <Launch size={12} /></a> : evidenceSourceLabels[source] ?? source}</span>) : '未登记'}</span>{editable && allowAccept && item.severity === 'blocking' && unresolved && <label className="kh-inline-accept"><input type="checkbox" checked={manuallyAccepted} onChange={() => toggleAccepted(item.check_code)} />人工核对后接受</label>}</footer>
      </article>;
    })}</div>;
}

interface IdentifierAssociationRow {
  code: string;
  label: string;
  status: string;
  source_value?: unknown;
  authoritative_value?: unknown;
}

function identifierAssociationRows(check: VerificationCheckView): IdentifierAssociationRow[] {
  const authoritative = isRecord(check.authoritative_value) ? check.authoritative_value : {};
  const source = isRecord(check.source_value) ? check.source_value : {};
  if (Array.isArray(authoritative.comparisons)) {
    return authoritative.comparisons.filter(isRecord).map((item, index) => ({
      code: typeof item.code === 'string' ? item.code : `comparison-${index}`,
      label: typeof item.label === 'string' ? item.label : '标识符关联',
      status: typeof item.status === 'string' ? item.status : 'pending',
      source_value: item.source_value,
      authoritative_value: item.authoritative_value,
    }));
  }
  const normalize = (value: unknown) => typeof value === 'string' || typeof value === 'number' ? `${value}`.trim().toLocaleLowerCase() : JSON.stringify(value ?? '');
  const equal = (left: unknown, right: unknown) => normalize(left) === normalize(right);
  const compare = (code: string, label: string, left: unknown, right: unknown, optional = false): IdentifierAssociationRow => ({
    code, label, source_value: left, authoritative_value: right,
    status: left && right ? (equal(left, right) ? 'passed' : 'conflict') : optional ? 'not_applicable' : 'missing',
  });
  const rows = [
    compare('source-crossref-doi', 'Excel DOI 与 Crossref DOI', source.doi, authoritative.crossref_doi),
    compare('crossref-pubmed-doi', 'Crossref DOI 与 PubMed DOI', authoritative.crossref_doi, authoritative.pubmed_doi),
  ];
  const pubmedPmid = authoritative.pubmed_pmid ?? source.pmid;
  const pubmedPmcid = authoritative.pubmed_pmcid;
  rows.push({
    code: 'pubmed-pmid-pmcid', label: 'PubMed PMID 与 PMCID 关联',
    source_value: pubmedPmid, authoritative_value: pubmedPmcid,
    status: pubmedPmid && pubmedPmcid ? 'passed' : 'not_applicable',
  });
  return rows;
}

function identifierAssociationStatus(check: VerificationCheckView) {
  const statuses = identifierAssociationRows(check).map((row) => row.status);
  if (statuses.includes('conflict')) return 'conflict';
  if (statuses.includes('passed')) return 'passed';
  return 'missing';
}

function effectiveCheckStatus(check: VerificationCheckView) {
  return check.check_code === 'identifier_triangle' ? identifierAssociationStatus(check) : check.check_status;
}

function checkDisplayLabel(check: VerificationCheckView) {
  return check.check_code === 'identifier_triangle' ? '标识符关联校验' : check.check_label;
}

function IdentifierAssociationCheck({ check, editable, accepted, toggleAccepted, sourceUrls }: {
  check: VerificationCheckView;
  editable: boolean;
  accepted: boolean;
  toggleAccepted: () => void;
  sourceUrls: Record<string, string | undefined>;
}) {
  const calculatedStatus = identifierAssociationStatus(check);
  const status = accepted ? 'passed' : calculatedStatus;
  const unresolved = ['conflict', 'missing', 'pending'].includes(calculatedStatus);
  const rows = identifierAssociationRows(check);
  return <article className={`kh-identifier-association is-${status}`}>
    <header><div><strong>标识符关联校验</strong><span>确认 DOI、PMID 与 PMCID 是否指向同一篇论文</span></div><div className="kh-field-status"><span className={`is-${status}`}>{status === 'passed' ? '通过' : status === 'conflict' ? '冲突' : '信息不足'}</span></div></header>
    <div className="kh-association-rows">{rows.map((row) => <div key={row.code} className={`is-${row.status}`}>
      <span className="kh-association-indicator" aria-hidden="true">{row.status === 'passed' ? '✓' : row.status === 'conflict' ? '×' : '–'}</span>
      <strong>{row.label}</strong>
      <small>{row.status === 'passed' ? '一致' : row.status === 'conflict' ? `${displayValue(row.source_value)} ↔ ${displayValue(row.authoritative_value)}` : '当前记录无须或暂无足够信息校验'}</small>
    </div>)}</div>
    <footer><span className="kh-check-sources">证据来源：{check.evidence_sources.map((source, index) => <span key={source}>{index > 0 && '、'}{sourceUrls[source] ? <a href={sourceUrls[source]} target="_blank" rel="noreferrer">{evidenceSourceLabels[source] ?? source} <Launch size={12} /></a> : evidenceSourceLabels[source] ?? source}</span>)}</span>{editable && check.severity === 'blocking' && unresolved && <label className="kh-inline-accept"><input type="checkbox" checked={accepted} onChange={toggleAccepted} />人工核对后接受</label>}</footer>
    <details className="kh-association-raw"><summary>查看标识符证据与原始 JSON</summary><div className="kh-field-options kh-evidence-options"><div className="kh-evidence-value"><span>来源记录</span><EvidenceValue value={check.source_value} /></div><div className="kh-evidence-value"><span>权威检索结果</span><EvidenceValue value={check.authoritative_value} /></div></div></details>
  </article>;
}

function AuthorAttributionSelector({ candidates, awardeeName, selectedOrder, setSelectedOrder,
  correspondingOrders, setCorrespondingOrders, coFirstOrders, setCoFirstOrders, editable }: {
  candidates: AuthorCandidate[];
  awardeeName: string | null;
  selectedOrder: number | null;
  setSelectedOrder: (order: number | null) => void;
  correspondingOrders: number[];
  setCorrespondingOrders: (orders: number[]) => void;
  coFirstOrders: number[];
  setCoFirstOrders: (orders: number[]) => void;
  editable: boolean;
}) {
  const toggle = (values: number[], order: number, setter: (orders: number[]) => void) =>
    setter(values.includes(order) ? values.filter((value) => value !== order) : [...values, order]);
  return <div className="kh-author-selector">
    <header><div><h3>获批人作者身份</h3><p>请确认“{awardeeName ?? '未登记获批人'}”对应的作者，并标记作者角色。</p></div><span>{selectedOrder ? `已选择第 ${selectedOrder} 作者` : '必须人工判断'}</span></header>
    {candidates.length ? <div className="kh-author-list">{candidates.map((author, index) => {
      const order = author.order ?? index + 1;
      return <div key={`${order}-${author.name ?? ''}`} className={selectedOrder === order ? 'selected' : ''}>
        <label><input type="radio" name="awardee-author" disabled={!editable} checked={selectedOrder === order} onChange={() => setSelectedOrder(order)} /><strong>{order}. {author.name ?? `${author.given ?? ''} ${author.family ?? ''}`}</strong></label>
        <span>{author.orcid ? `ORCID ${author.orcid}` : '无 ORCID'}{author.affiliations?.length ? ` · ${author.affiliations.join('; ')}` : ''}</span>
        <div><label><input type="checkbox" disabled={!editable} checked={coFirstOrders.includes(order)} onChange={() => toggle(coFirstOrders, order, setCoFirstOrders)} />共同第一作者</label><label><input type="checkbox" disabled={!editable} checked={correspondingOrders.includes(order)} onChange={() => toggle(correspondingOrders, order, setCorrespondingOrders)} />通讯作者</label></div>
      </div>;
    })}</div> : <InlineNotification lowContrast hideCloseButton kind="warning" title="权威来源没有返回可选作者列表" subtitle="可先完成论文身份核验，但成果归属层将保持待补齐。" />}
    {editable && selectedOrder && <Button size="sm" kind="ghost" onClick={() => setSelectedOrder(null)}>清除作者匹配</Button>}
  </div>;
}

function parseObjectJson(value: string, label: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(value || '{}');
    if (!isRecord(parsed)) throw new Error();
    return parsed;
  } catch {
    throw new Error(`${label}必须是一个 JSON 对象`);
  }
}

function FulltextExtractionCard({ resource }: { resource: PublicationFulltextResourceView }) {
  const extraction = isRecord(resource.extracted_metadata?.fulltext_extraction)
    ? resource.extracted_metadata.fulltext_extraction : {};
  const keywords = Array.isArray(extraction.keywords) ? extraction.keywords.map(String) : [];
  const sections = Array.isArray(extraction.section_headings)
    ? extraction.section_headings.map(String) : [];
  return <article className="kh-fulltext-result">
    <header><div><DocumentView size={20} /><span><strong>{resource.file_name}</strong><small>{resource.resource_role === 'correction' ? '勘误文件' : resource.resource_role === 'supplementary' ? '补充材料' : '论文全文'} · {resource.page_count ?? '—'} 页 · {resource.text_length?.toLocaleString('zh-CN') ?? '—'} 字符</small></span></div><span className={`is-${resource.extraction_state}`}>{resource.extraction_state === 'extracted' ? '已解析' : resource.extraction_state === 'failed' ? '解析失败' : '等待解析'}</span></header>
    <div className="kh-fulltext-method"><span>处理方式：{resource.extraction_method === 'ocr' ? `OCR（${resource.ocr_page_count ?? 0} 页）` : '原生文本层'}</span><span>解析规则：{resource.extraction_version ?? '待运行'}</span></div>
    {typeof extraction.abstract === 'string' && extraction.abstract && <details open><summary>摘要</summary><p>{extraction.abstract}</p></details>}
    {keywords.length > 0 && <div className="kh-fulltext-tags"><strong>关键词</strong>{keywords.map((item) => <span key={item}>{item}</span>)}</div>}
    {sections.length > 0 && <div className="kh-fulltext-tags"><strong>识别章节</strong>{sections.map((item) => <span key={item}>{item}</span>)}</div>}
    {typeof extraction.funding_text === 'string' && extraction.funding_text && <details><summary>基金与资助文本</summary><p>{extraction.funding_text}</p></details>}
    <details><summary>查看结构化结果</summary><EvidenceValue value={extraction} /></details>
  </article>;
}

function IncrementalSupplementPanel({ detail, canSubmit, canDecide }: {
  detail: PublicationVerificationDetail;
  canSubmit: boolean | undefined;
  canDecide: boolean | undefined;
}) {
  const publicationId = detail.matched_publication_id;
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [sourceKind, setSourceKind] = useState<PublicationSupplementCreate['source_kind']>('metadata');
  const [sourceLabel, setSourceLabel] = useState('后续人工补充');
  const [sourceUri, setSourceUri] = useState('');
  const [note, setNote] = useState('');
  const [metadataJson, setMetadataJson] = useState('{}');
  const [doi, setDoi] = useState('');
  const [pmid, setPmid] = useState('');
  const [pmcid, setPmcid] = useState('');
  const [funderName, setFunderName] = useState('');
  const [grantId, setGrantId] = useState('');
  const [fundingCountry, setFundingCountry] = useState('');
  const [fulltextFile, setFulltextFile] = useState<File | null>(null);
  const [fulltextResourceRole, setFulltextResourceRole] = useState<'article' | 'correction' | 'supplementary'>('article');
  const [selectedCandidates, setSelectedCandidates] = useState<Set<string>>(new Set());
  const [reviewReason, setReviewReason] = useState('已核对新增证据与当前权威记录。');

  const supplements = useQuery({
    queryKey: ['publication-supplements', publicationId],
    queryFn: () => {
      if (!publicationId) throw new Error('论文尚未形成权威记录');
      return getPublicationSupplementsView(publicationId);
    },
    enabled: Boolean(publicationId),
  });
  const fulltexts = useQuery({
    queryKey: ['publication-fulltexts', publicationId],
    queryFn: () => {
      if (!publicationId) throw new Error('论文尚未形成权威记录');
      return getPublicationFulltextsView(publicationId);
    },
    enabled: Boolean(publicationId),
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['publication-supplements', publicationId] }),
      queryClient.invalidateQueries({ queryKey: ['publication-fulltexts', publicationId] }),
      queryClient.invalidateQueries({ queryKey: ['publication-verification', detail.record_id] }),
      queryClient.invalidateQueries({ queryKey: ['knowledge-hub-overview'] }),
    ]);
  };
  const submit = useMutation({
    mutationFn: async () => {
      if (!publicationId) throw new Error('论文尚未形成权威记录');
      if (sourceKind === 'fulltext') {
        if (!fulltextFile) throw new Error('请先选择论文 PDF 文件');
        return uploadPublicationFulltextView(
          publicationId, fulltextFile, sourceLabel.trim(), fulltextResourceRole,
          note.trim() || undefined,
        );
      }
      const command: PublicationSupplementCreate = {
        source_kind: sourceKind,
        source_label: sourceLabel.trim(),
        source_uri: sourceUri.trim() || undefined,
        note: note.trim() || undefined,
      };
      if (sourceKind === 'metadata' || sourceKind === 'lifecycle') {
        command.metadata = parseObjectJson(metadataJson, '补充信息');
      }
      if (sourceKind === 'identifier') {
        command.identifiers = {
          doi: doi.trim() || undefined,
          pmid: pmid.trim() || undefined,
          pmcid: pmcid.trim() || undefined,
        };
      }
      if (sourceKind === 'funding') {
        command.funding = [{
          funder_name: funderName.trim(),
          grant_id: grantId.trim() || undefined,
          country: fundingCountry.trim() || undefined,
        }];
      }
      return submitPublicationSupplementView(publicationId, command);
    },
    onSuccess: async () => { setFormOpen(false); setFulltextFile(null); await refresh(); },
  });
  const decide = useMutation({
    mutationFn: ({ supplement, decision }: { supplement: PublicationSupplementView; decision: 'accept' | 'reject' }) => {
      const available = (supplement.candidates ?? [])
        .filter((candidate) => candidate.status === 'pending')
        .map((candidate) => candidate.proposal_id);
      const chosen = available.filter((candidateId) => selectedCandidates.has(candidateId));
      if (!chosen.length) throw new Error('请先选择要处理的变更项');
      return decidePublicationSupplementView(supplement.submission_id, {
        decision, reason: reviewReason.trim(), proposal_ids: chosen,
      });
    },
    onSuccess: async () => { setSelectedCandidates(new Set()); await refresh(); },
  });
  const toggleCandidate = (candidateId: string) => setSelectedCandidates((current) => {
    const next = new Set(current);
    if (next.has(candidateId)) next.delete(candidateId); else next.add(candidateId);
    return next;
  });
  const status = detail.incremental_status;
  const sourceSpecificReady = sourceKind === 'identifier' ? Boolean(doi.trim() || pmid.trim() || pmcid.trim())
    : sourceKind === 'funding' ? Boolean(funderName.trim())
      : sourceKind === 'fulltext' ? Boolean(fulltextFile && fulltextFile.name.toLowerCase().endsWith('.pdf') && fulltextFile.size <= 100 * 1024 * 1024)
        : metadataJson.trim().length > 2 && metadataJson.trim() !== '{}';

  if (!publicationId) return <section className="kh-review-section kh-supplement-section"><header><div><h3>后续信息与版本</h3><p>完成论文身份确认后，才能登记全文、基金和后续出版信息。</p></div></header></section>;
  return <section className="kh-review-section kh-supplement-section">
    <header><div><h3>后续信息与版本</h3><p>新证据不会覆盖历史记录；安全新增自动写回，身份变化和冲突项进入人工确认。</p></div>{canSubmit && <Button size="sm" kind="tertiary" onClick={() => setFormOpen(true)}>录入后续信息</Button>}</header>
    {status && <div className="kh-incremental-status">
      <span><small>当前版本</small><strong>v{status.metadata_version}</strong></span>
      <span><small>论文身份</small><strong>{status.identity_state === 'verified' ? '已确认' : '需要复核'}</strong></span>
      <span><small>信息完整度</small><strong>{status.enrichment_state === 'review_required' ? '有待确认项' : status.enrichment_state === 'complete' ? '完整' : '可继续补充'}</strong></span>
      <span><small>全文</small><strong>{status.fulltext_state === 'missing' ? '尚未登记' : status.fulltext_state === 'extracted' ? '已解析' : '已登记'}</strong></span>
      <span><small>待处理</small><strong>{status.open_supplement_count}</strong></span>
    </div>}
    {fulltexts.isError && <InlineNotification lowContrast kind="error" title="全文解析结果加载失败" subtitle={fulltexts.error.message} />}
    {fulltexts.data && fulltexts.data.length > 0 && <div className="kh-fulltext-results">
      <h4>全文解析结果</h4>
      {fulltexts.data.map((resource) => <FulltextExtractionCard key={resource.fulltext_resource_id} resource={resource} />)}
    </div>}
    {supplements.isPending ? <div className="kh-supplement-loading"><SkeletonText paragraph lineCount={3} /></div>
      : supplements.isError ? <InlineNotification lowContrast kind="error" title="后续记录加载失败" subtitle={supplements.error.message} />
        : supplements.data.length ? <div className="kh-supplement-list">{supplements.data.map((item) => {
          const pending = (item.candidates ?? []).filter((candidate) => candidate.status === 'pending');
          return <article key={item.submission_id} className={`kh-supplement-card is-${item.status}`}>
            <header><div><strong>{item.source_label}</strong><span>{supplementKindLabels[item.source_kind] ?? item.source_kind} · {new Date(item.created_at).toLocaleString('zh-CN')}</span></div><span>{supplementStatusLabels[item.status] ?? item.status}</span></header>
            <div className="kh-supplement-version">基于 v{item.base_version}{item.applied_version ? `，已写入 v${item.applied_version}` : ''} · {item.impact === 'critical' ? '涉及论文身份' : item.impact === 'corrective' ? '包含修正' : '补充新增'}</div>
            <div className="kh-candidate-list">{(item.candidates ?? []).map((candidate) => <label key={candidate.proposal_id} className={`kh-candidate is-${candidate.status}`}>
              {candidate.status === 'pending' && canDecide ? <input type="checkbox" checked={selectedCandidates.has(candidate.proposal_id)} onChange={() => toggleCandidate(candidate.proposal_id)} /> : <span className="kh-candidate-mark">{candidate.status === 'rejected' ? '×' : '✓'}</span>}
              <span><strong>{candidateFieldLabels[candidate.field_path] ?? candidate.field_path}</strong><small>{candidate.risk_level === 'critical' ? '身份关键项' : candidate.risk_level === 'review' ? '需人工判断' : '安全新增'}</small></span>
              <span className="kh-candidate-values">{candidate.application_state === 'conflict' && <small role="alert">版本已变化，请拒绝此项并基于最新信息重新提交。</small>}<del>{displayValue(candidate.current_value)}</del><b>→</b><ins>{displayValue(candidate.proposed_value)}</ins></span>
            </label>)}</div>
            {pending.length > 0 && canDecide && <div className="kh-supplement-review"><TextArea id={`review-${item.submission_id}`} labelText="处理说明" rows={2} value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} /><div><Button size="sm" kind="danger--tertiary" disabled={decide.isPending || !pending.some((candidate) => selectedCandidates.has(candidate.proposal_id))} onClick={() => decide.mutate({ supplement: item, decision: 'reject' })}>拒绝所选</Button><Button size="sm" disabled={decide.isPending || !pending.some((candidate) => selectedCandidates.has(candidate.proposal_id))} onClick={() => decide.mutate({ supplement: item, decision: 'accept' })}>接受并写回</Button></div></div>}
          </article>;
        })}</div> : <p className="kh-supplement-empty">尚无后续补充记录。以后导入全文、基金或出版状态时，会从这里进入版本化核验。</p>}
    {decide.isError && <InlineNotification lowContrast kind="error" title="变更处理失败" subtitle={decide.error.message} />}
    <Modal open={formOpen} modalHeading="录入论文后续信息" primaryButtonText={submit.isPending ? (sourceKind === 'fulltext' ? '正在上传、解析并登记…' : '正在登记…') : (sourceKind === 'fulltext' ? '上传、解析并进入核验' : '登记并分析差异')} secondaryButtonText="取消" primaryButtonDisabled={!sourceLabel.trim() || !sourceSpecificReady || submit.isPending} onRequestClose={() => setFormOpen(false)} onRequestSubmit={() => submit.mutate()}>
      <div className="kh-supplement-form">
        <Select id="supplement-kind" labelText="信息类型" value={sourceKind} onChange={(event) => { const next = event.target.value as PublicationSupplementCreate['source_kind']; setSourceKind(next); if (next === 'fulltext' && sourceLabel === '后续人工补充') setSourceLabel('人工上传论文全文'); }}>{Object.entries(supplementKindLabels).map(([value, label]) => <SelectItem key={value} value={value} text={label} />)}</Select>
        <TextInput id="supplement-source-label" labelText="来源名称" value={sourceLabel} onChange={(event) => setSourceLabel(event.target.value)} />
        {sourceKind !== 'fulltext' && <TextInput id="supplement-source-uri" labelText="来源地址（选填）" value={sourceUri} onChange={(event) => setSourceUri(event.target.value)} />}
        {(sourceKind === 'metadata' || sourceKind === 'lifecycle') && <TextArea id="supplement-metadata" labelText="补充字段（JSON 对象）" helperText={'例如：{"abstract":"...","keywords":["肿瘤"]}'} rows={6} value={metadataJson} onChange={(event) => setMetadataJson(event.target.value)} />}
        {sourceKind === 'identifier' && <div className="kh-supplement-fields"><TextInput id="supplement-doi" labelText="DOI" value={doi} onChange={(event) => setDoi(event.target.value)} /><TextInput id="supplement-pmid" labelText="PMID" value={pmid} onChange={(event) => setPmid(event.target.value)} /><TextInput id="supplement-pmcid" labelText="PMCID" value={pmcid} onChange={(event) => setPmcid(event.target.value)} /></div>}
        {sourceKind === 'funding' && <div className="kh-supplement-fields"><TextInput id="supplement-funder" labelText="资助机构" value={funderName} onChange={(event) => setFunderName(event.target.value)} /><TextInput id="supplement-grant" labelText="基金编号（选填）" value={grantId} onChange={(event) => setGrantId(event.target.value)} /><TextInput id="supplement-country" labelText="国家或地区（选填）" value={fundingCountry} onChange={(event) => setFundingCountry(event.target.value)} /></div>}
        {sourceKind === 'fulltext' && <div className="kh-fulltext-upload">
          <Select id="supplement-fulltext-role" labelText="PDF 类型" value={fulltextResourceRole} onChange={(event) => { const nextRole = event.target.value as 'article' | 'correction' | 'supplementary'; setFulltextResourceRole(nextRole); if (sourceLabel === '人工上传论文全文' || sourceLabel === '人工上传论文勘误文件' || sourceLabel === '人工上传论文补充材料') setSourceLabel(nextRole === 'correction' ? '人工上传论文勘误文件' : nextRole === 'supplementary' ? '人工上传论文补充材料' : '人工上传论文全文'); }}><SelectItem value="article" text="论文全文" /><SelectItem value="correction" text="勘误文件" /><SelectItem value="supplementary" text="补充材料" /></Select>
          <label htmlFor="supplement-fulltext-file"><strong>{fulltextResourceRole === 'correction' ? '勘误 PDF' : '论文全文 PDF'}</strong><span>文件将上传到受控对象存储；系统自动计算 SHA-256、文件大小和存储地址。</span></label>
          <input id="supplement-fulltext-file" type="file" accept="application/pdf,.pdf" onChange={(event) => setFulltextFile(event.target.files?.[0] ?? null)} />
          {fulltextFile && <div className="kh-upload-selection"><DocumentView size={20} /><span><strong>{fulltextFile.name}</strong><small>{(fulltextFile.size / 1024 / 1024).toFixed(2)} MB · {fulltextFile.size <= 100 * 1024 * 1024 ? '可以上传' : '超过 100 MB 限制'}</small></span></div>}
        </div>}
        <TextArea id="supplement-note" labelText="说明（选填）" rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
        {submit.isError && <InlineNotification lowContrast kind="error" title="登记失败" subtitle={submit.error.message} />}
      </div>
    </Modal>
  </section>;
}

function VerificationDrawer({ detail, canDecide, canSupplementSubmit, canSupplementDecide, close, onDecision }: {
  detail: PublicationVerificationDetail;
  canDecide: boolean | undefined;
  canSupplementSubmit: boolean;
  canSupplementDecide: boolean;
  close: () => void;
  onDecision: (kind: 'confirm' | 'reject', selection: DecisionSelection) => void;
}) {
  const isManualReview = detail.verification_state === 'manual_review';
  const hasOpenLayers = detail.layers?.some((layer) => layer.layer_status !== 'passed');
  const editable = Boolean(canDecide && (isManualReview || hasOpenLayers));
  const [choices, setChoices] = useState<Record<string, 'source' | 'candidate'>>(() =>
    Object.fromEntries(detail.fields.map((field) => [
      field.field_name,
      field.verification_status === 'matched' && field.candidate_value !== null ? 'candidate' : 'source',
    ])),
  );
  const [acceptedChecks, setAcceptedChecks] = useState<Set<string>>(new Set());
  const [awardeeAuthorOrder, setAwardeeAuthorOrder] = useState<number | null>(null);
  const [correspondingOrders, setCorrespondingOrders] = useState<number[]>([]);
  const [coFirstOrders, setCoFirstOrders] = useState<number[]>([]);
  const candidates = authorCandidates(detail);
  const identityChecks = detail.layers?.find((layer) => layer.layer_code === 'identity')?.checks ?? [];
  const attributionChecks = detail.layers?.find((layer) => layer.layer_code === 'attribution')?.checks ?? [];
  const enrichmentChecks = detail.layers?.find((layer) => layer.layer_code === 'enrichment')?.checks ?? [];
  const fieldCheckCodes: Record<string, string> = {
    title: 'title', journal_name: 'journal', publication_year: 'publication_year',
    doi: 'doi', pmid: 'pmid', pmcid: 'pmcid',
  };
  const fieldCheck = (fieldName: string) => identityChecks.find((check) => check.check_code === fieldCheckCodes[fieldName]);
  const supportingIdentityChecks = identityChecks.filter((check) => !Object.values(fieldCheckCodes).includes(check.check_code));
  const identifierAssociation = supportingIdentityChecks.find((check) => check.check_code === 'identifier_triangle');
  const remainingIdentityChecks = supportingIdentityChecks.filter((check) => check.check_code !== 'identifier_triangle');
  const supportingAttributionChecks = attributionChecks.filter((check) => !['awardee_author_match', 'author_list_available'].includes(check.check_code));
  const allChecks = (detail.layers ?? []).flatMap((layer) => layer.checks);
  const passedCount = allChecks.filter((check) => effectiveCheckStatus(check) === 'passed').length;
  const conflictCount = allChecks.filter((check) => effectiveCheckStatus(check) === 'conflict').length;
  const openCount = allChecks.filter((check) => ['missing', 'pending'].includes(effectiveCheckStatus(check))).length;
  const doiForUrl = typeof detail.normalized_payload.doi === 'string' ? detail.normalized_payload.doi : undefined;
  const pmidForUrl = typeof detail.normalized_payload.pmid === 'string' ? detail.normalized_payload.pmid : undefined;
  const sourceUrls = {
    crossref: doiForUrl ? `https://api.crossref.org/works/${doiForUrl}` : undefined,
    ncbi_pubmed: pmidForUrl ? `https://pubmed.ncbi.nlm.nih.gov/${pmidForUrl}/` : undefined,
  };
  const fieldsByName = new Map(detail.fields.map((field) => [field.field_name, field]));
  const renderField = (fieldName: string) => {
    const field = fieldsByName.get(fieldName);
    if (!field) return null;
    const check = fieldCheck(field.field_name);
    return <FieldComparison key={field.field_name} field={field} check={check} editable={editable} accepted={Boolean(check && acceptedChecks.has(check.check_code))} toggleAccepted={() => check && setAcceptedChecks((current) => { const next = new Set(current); if (next.has(check.check_code)) next.delete(check.check_code); else next.add(check.check_code); return next; })} choice={choices[field.field_name] ?? 'source'} setChoice={(choice) => setChoices((current) => ({ ...current, [field.field_name]: choice }))} />;
  };
  const renderIdentifierField = (fieldName: 'doi' | 'pmid' | 'pmcid') => {
    const field = fieldsByName.get(fieldName);
    if (field) return renderField(fieldName);
    return <MissingIdentifierField key={fieldName} fieldName={fieldName} sourceValue={detail.normalized_payload[fieldName]} check={fieldCheck(fieldName)} />;
  };
  const decisionSelection: DecisionSelection = {
    choices,
    acceptedCheckCodes: [...acceptedChecks],
    awardeeAuthorOrder,
    correspondingAuthorOrders: correspondingOrders,
    coFirstAuthorOrders: coFirstOrders,
  };
  const resolvedCheckCodes = new Set(acceptedChecks);
  if (awardeeAuthorOrder) resolvedCheckCodes.add('awardee_author_match');
  if (correspondingOrders.length) resolvedCheckCodes.add('corresponding_author');
  const unresolvedBlockingChecks = allChecks.filter((check) =>
    check.severity === 'blocking'
    && ['conflict', 'missing', 'pending'].includes(effectiveCheckStatus(check))
    && !resolvedCheckCodes.has(check.check_code),
  );
  return <div className="kh-drawer-layer"><button className="kh-drawer-scrim" aria-label="关闭论文核验详情" onClick={close} /><aside className="kh-review-drawer" role="dialog" aria-modal="true" aria-labelledby="kh-review-title">
    <header className="kh-drawer-header"><div><span>来源行 {detail.source_row_number} · {detail.awardee_name ?? '获批人未登记'}</span><h2 id="kh-review-title">{displayValue(detail.normalized_payload.title)}</h2></div><Button kind="ghost" hasIconOnly renderIcon={Close} iconDescription="关闭" onClick={close} /></header>
    <section className="kh-review-summary"><span><small>记录状态</small><strong>{stateLabels[detail.verification_state] ?? detail.verification_state}</strong></span><span><small>已通过</small><strong>{passedCount}</strong></span><span><small>冲突</small><strong>{conflictCount}</strong></span><span><small>待确认或补充</small><strong>{openCount}</strong></span></section>
    <div className="kh-evidence-note"><DocumentView size={18} /><p>按审核顺序核对论文信息、作者归属和补充信息。相同字段只展示一次，选择结果与人工判断会进入审计记录。</p></div>
    {detail.fulltext_preverification && <FulltextPreverificationCard result={detail.fulltext_preverification} />}
    <section className="kh-review-section"><header><div><h3>论文基本信息</h3><p>核对题名、期刊和发表年份，并选择最终写入值。</p></div></header><div className="kh-field-list">{['title', 'journal_name', 'publication_year'].map(renderField)}</div></section>
    <section className="kh-review-section"><header><div><h3>标识符与论文状态</h3><p>先分别确定 DOI、PMID、PMCID 的最终值，再检查这些标识符是否属于同一篇论文。</p></div></header><div className="kh-field-list">{(['doi', 'pmid', 'pmcid'] as const).map(renderIdentifierField)}</div>{identifierAssociation && <IdentifierAssociationCheck check={identifierAssociation} editable={editable} accepted={acceptedChecks.has(identifierAssociation.check_code)} sourceUrls={sourceUrls} toggleAccepted={() => setAcceptedChecks((current) => { const next = new Set(current); if (next.has(identifierAssociation.check_code)) next.delete(identifierAssociation.check_code); else next.add(identifierAssociation.check_code); return next; })} />}<EvidenceChecks checks={remainingIdentityChecks} editable={editable} accepted={acceptedChecks} sourceUrls={sourceUrls} allowAccept toggleAccepted={(code) => setAcceptedChecks((current) => { const next = new Set(current); if (next.has(code)) next.delete(code); else next.add(code); return next; })} /></section>
    <section className="kh-review-section"><header><div><h3>作者与成果归属</h3><p>确认获批人对应作者，并核对作者顺序、单位、ORCID 和通讯作者信息。</p></div></header>{detail.layers?.some((layer) => layer.layer_code === 'attribution') && <AuthorAttributionSelector candidates={candidates} awardeeName={detail.awardee_name} selectedOrder={awardeeAuthorOrder} setSelectedOrder={setAwardeeAuthorOrder} correspondingOrders={correspondingOrders} setCorrespondingOrders={setCorrespondingOrders} coFirstOrders={coFirstOrders} setCoFirstOrders={setCoFirstOrders} editable={editable} />}<EvidenceChecks checks={supportingAttributionChecks} editable={editable} accepted={acceptedChecks} sourceUrls={sourceUrls} allowAccept toggleAccepted={(code) => setAcceptedChecks((current) => { const next = new Set(current); if (next.has(code)) next.delete(code); else next.add(code); return next; })} /></section>
    <section className="kh-review-section"><header><div><h3>内容与出版信息</h3><p>查看摘要、主题词、具体出版日期、开放获取和基金资助等补充结果。</p></div></header><EvidenceChecks checks={enrichmentChecks} editable={editable} accepted={acceptedChecks} sourceUrls={sourceUrls} toggleAccepted={() => undefined} /></section>
    <IncrementalSupplementPanel detail={detail} canSubmit={canSupplementSubmit} canDecide={canSupplementDecide} />
    {detail.current_decision && <section className="kh-current-decision"><h3>当前核验决定</h3><p>{detail.current_decision.decision_reason}</p><small>{detail.current_decision.decision} · {new Date(detail.current_decision.decided_at).toLocaleString('zh-CN')}</small></section>}
    <section className="kh-audit-trail"><h3>该记录的操作审计</h3>{detail.audit_events.length ? detail.audit_events.map((event, index) => <div key={displayValue(event.event_id ?? index)}><strong>{displayValue(event.action)}</strong><span>{new Date(displayValue(event.occurred_at)).toLocaleString('zh-CN')} · {displayValue(event.decision)}</span></div>) : <p>打开详情后产生的读取审计将在下次刷新显示。</p>}</section>
    <footer className="kh-drawer-actions">{editable ? <><div className={`kh-submit-gate ${unresolvedBlockingChecks.length ? 'has-blockers' : 'is-ready'}`}><strong>{unresolvedBlockingChecks.length ? `还有 ${unresolvedBlockingChecks.length} 个阻断项未处理` : '所有阻断项均已处理'}</strong>{unresolvedBlockingChecks.length > 0 && <span>{unresolvedBlockingChecks.map(checkDisplayLabel).join('、')}</span>}</div>{isManualReview && <Button kind="danger--tertiary" renderIcon={Close} onClick={() => onDecision('reject', decisionSelection)}>驳回记录</Button>}<Button renderIcon={Checkmark} disabled={unresolvedBlockingChecks.length > 0} onClick={() => onDecision('confirm', decisionSelection)}>{isManualReview ? '确认并写回' : '保存核验结果'}</Button></> : <InlineNotification lowContrast hideCloseButton kind={canDecide ? 'info' : 'warning'} title={canDecide ? '核验已完成' : '当前角色只有查看权限'} />}</footer>
  </aside></div>;
}

export function PublicationVerificationWorkbench() {
  const { permissions } = useOutletContext<KnowledgeHubOutletContext>();
  const queryClient = useQueryClient();
  const [state, setState] = useState('');
  const [fulltextStatus, setFulltextStatus] = useState('');
  const [searchDraft, setSearchDraft] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [decision, setDecision] = useState<{
    kind: 'confirm' | 'reject'; selection: DecisionSelection;
  } | null>(null);
  const [reason, setReason] = useState('已核对原始著录与外部权威来源，确认所选字段。');

  const queue = useQuery({
    queryKey: ['publication-verifications', state, fulltextStatus, query, page, pageSize],
    queryFn: () => getPublicationVerificationPage({
      state, fulltextStatus, query, page, pageSize,
    }),
  });
  const detail = useQuery({
    queryKey: ['publication-verification', selectedId],
    queryFn: () => {
      if (!selectedId) throw new Error('未选择论文核验记录');
      return getPublicationVerificationView(selectedId);
    },
    enabled: Boolean(selectedId),
  });
  const submit = useMutation({
    mutationFn: async () => {
      if (!selectedId || !decision) throw new Error('核验决定缺少目标记录');
      const command = decision.kind === 'reject' ? { reason } : {
          reason,
          field_choices: decision.selection.choices,
          accepted_check_codes: decision.selection.acceptedCheckCodes,
          awardee_author_order: decision.selection.awardeeAuthorOrder,
          corresponding_author_orders: decision.selection.correspondingAuthorOrders,
          co_first_author_orders: decision.selection.coFirstAuthorOrders,
        };
      return submitPublicationVerification(selectedId, command, decision.kind);
    },
    onSuccess: async () => {
      setDecision(null);
      setSelectedId(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['publication-verifications'] }),
        queryClient.invalidateQueries({ queryKey: ['knowledge-hub-overview'] }),
      ]);
    },
  });

  return <div className="kh-page kh-workbench">
    <WorkbenchHeader />
    <section className="kh-queue-toolbar" aria-label="论文核验筛选">
      <form onSubmit={(event) => { event.preventDefault(); setPage(1); setQuery(searchDraft.trim()); }}>
        <Search labelText="搜索论文核验队列" placeholder="题名、获批人、DOI 或 PMID" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} />
        <Button type="submit" renderIcon={SearchIcon}>搜索</Button>
      </form>
      <Select id="verification-state" labelText="核验状态" value={state} onChange={(event) => { setState(event.target.value); setPage(1); }}>
        <SelectItem value="" text="全部状态" />
        {Object.entries(stateLabels).map(([value, text]) => <SelectItem key={value} value={value} text={`${text}${queue.data?.state_counts[value] !== undefined ? ` (${queue.data.state_counts[value]})` : ''}`} />)}
      </Select>
      <Select id="fulltext-preverification-state" labelText="全文预核验" value={fulltextStatus} onChange={(event) => { setFulltextStatus(event.target.value); setPage(1); }}>
        <SelectItem value="" text="全部全文状态" />
        {Object.entries(preverificationStatusLabels).map(([value, label]) => (
          <SelectItem
            key={value}
            value={value}
            text={`${label}${queue.data?.fulltext_preverification_counts?.[value] !== undefined ? ` (${queue.data.fulltext_preverification_counts[value]})` : ''}`}
          />
        ))}
      </Select>
      <Button kind="ghost" renderIcon={Renew} onClick={() => void queue.refetch()}>刷新</Button>
    </section>

    {queue.isPending ? <section className="kh-table-loading"><SkeletonText heading /><SkeletonText paragraph lineCount={8} /></section>
      : queue.isError ? <InlineNotification kind="error" title="核验队列加载失败" subtitle={queue.error.message} actions={<Button kind="ghost" onClick={() => void queue.refetch()}>重试</Button>} />
        : <section className="kh-table-section">
          <div className="kh-table-summary"><strong>{queue.data.total}</strong><span>条符合当前条件</span><small>长题名和标识符保持完整，可打开详情查看字段证据</small></div>
          {queue.data.items.length ? <>
            <TableContainer>
              <Table size="lg" useZebraStyles={false}>
                <TableHead><TableRow>
                  {['来源行', '论文与标识符', '获批人', '发表信息', '核验摘要', '状态', '操作'].map((label) => <TableHeader key={label}>{label}</TableHeader>)}
                </TableRow></TableHead>
                <TableBody>{queue.data.items.map((item) => <TableRow key={item.record_id}>
                  <TableCell><code>{item.source_row_number}</code></TableCell>
                  <TableCell><button className="kh-title-button" onClick={() => setSelectedId(item.record_id)}><strong>{item.title}</strong><span>{item.identifiers.doi ? `DOI ${item.identifiers.doi}` : item.identifiers.pmid ? `PMID ${item.identifiers.pmid}` : '无外部标识符'}</span></button></TableCell>
                  <TableCell>{item.awardee_name ?? '—'}</TableCell>
                  <TableCell><span className="kh-cell-stack"><strong>{item.journal_name ?? '期刊未登记'}</strong><small>{item.publication_year ?? '年份未登记'}</small></span></TableCell>
                  <TableCell><div className="kh-layer-statuses">{item.fulltext_preverification_status && <span className={`is-pre-${item.fulltext_preverification_status}`}>全文 · {preverificationStatusLabels[item.fulltext_preverification_status] ?? item.fulltext_preverification_status}</span>}{['identity', 'attribution', 'enrichment'].map((code) => <span key={code} className={`is-${item.layer_statuses?.[code] ?? 'pending'}`}>{reviewAreaLabels[code]} · {layerStatusLabels[item.layer_statuses?.[code] ?? 'pending']}</span>)}</div></TableCell>
                  <TableCell>{stateLabels[item.verification_state] ?? item.verification_state}</TableCell>
                  <TableCell><Button kind="ghost" size="sm" onClick={() => setSelectedId(item.record_id)}>查看证据</Button></TableCell>
                </TableRow>)}</TableBody>
              </Table>
            </TableContainer>
            <Pagination page={page} pageSize={pageSize} pageSizes={[10, 20, 50]} totalItems={queue.data.total} onChange={({ page: nextPage, pageSize: nextSize }) => { setPage(nextPage); setPageSize(nextSize); }} />
          </> : <div className="kh-empty"><SearchIcon size={28} /><h2>{query ? '没有符合条件的记录' : '当前队列为空'}</h2><p>{query ? '请调整关键词或核验状态。' : '该状态下没有需要处理的论文记录。'}</p>{query && <Button kind="tertiary" onClick={() => { setSearchDraft(''); setQuery(''); }}>清除搜索</Button>}</div>}
        </section>}

    {selectedId && detail.isPending && <div className="kh-detail-loading"><Loading description="正在加载来源证据" withOverlay /></div>}
    {selectedId && detail.isError && <div className="kh-drawer-layer"><button className="kh-drawer-scrim" aria-label="关闭" onClick={() => setSelectedId(null)} /><aside className="kh-review-drawer kh-detail-error"><InlineNotification kind="error" title="论文详情加载失败" subtitle={detail.error.message} /><Button kind="secondary" onClick={() => void detail.refetch()}>重试</Button><Button kind="ghost" onClick={() => setSelectedId(null)}>关闭</Button></aside></div>}
    {selectedId && detail.data && <VerificationDrawer key={selectedId} detail={detail.data} canDecide={permissions.includes('publication_verification.decide')} canSupplementSubmit={permissions.includes('publication_supplement.submit')} canSupplementDecide={permissions.includes('publication_supplement.decide')} close={() => setSelectedId(null)} onDecision={(kind, selection) => { setDecision({ kind, selection }); setReason(kind === 'confirm' ? '已核对论文身份、成果归属与外部权威来源，确认所选字段和作者身份。' : '权威来源证据不足或与来源记录无法安全对应。'); }} />}

    <Modal open={Boolean(decision)} danger={decision?.kind === 'reject'} modalHeading={decision?.kind === 'confirm' ? '确认并写回权威记录' : '驳回这条来源记录'} primaryButtonText={submit.isPending ? '正在写入…' : decision?.kind === 'confirm' ? '确认写回' : '确认驳回'} secondaryButtonText="取消" primaryButtonDisabled={reason.trim().length < 3 || submit.isPending} onRequestClose={() => setDecision(null)} onRequestSubmit={() => submit.mutate()}>
      <p className="kh-modal-impact">{decision?.kind === 'confirm' ? '将写入 PostgreSQL 权威论文、标识符、来源证据、学者关系、核验决定和待投影事件；HugeGraph 与 OpenSearch 由投影任务更新。' : '不会删除来源记录；记录将标记为已驳回，并保留原因和审计历史。'}</p>
      <TextArea id="decision-reason" labelText="审核理由（必填）" value={reason} onChange={(event) => setReason(event.target.value)} />
      {submit.isError && <InlineNotification lowContrast kind="error" title="决定写入失败" subtitle={submit.error.message} />}
    </Modal>
  </div>;
}
