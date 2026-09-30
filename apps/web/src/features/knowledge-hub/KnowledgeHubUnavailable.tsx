import { Construction } from '@carbon/icons-react';

export function KnowledgeHubUnavailable() {
  return <section className="kh-boundary"><Construction size={32} /><h1>该管理模块待建设</h1><p>此入口为规划功能，尚未提供操作能力。现有导入、核验、分类治理和版本追溯可通过左侧菜单访问。</p><a className="cds--btn cds--btn--primary" href="/knowledge-hub/verifications/publications">进入论文核验</a></section>;
}
