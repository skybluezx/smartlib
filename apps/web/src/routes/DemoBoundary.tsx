import type { ReactNode } from 'react';
import { InfoIcon as Info } from '@phosphor-icons/react';
import { runtimeConfig } from '../shared/config/runtime';

export function DemoBoundary({ children }: { children: ReactNode }) {
  if (runtimeConfig.demoMode) return children;
  return <section className="panel empty-state"><Info size={28} /><strong>能力模块尚未接入生产数据</strong><p>当前正式构建已关闭演示数据。后续领域服务接入后，本路由和交互契约保持不变。</p></section>;
}
