import { InfoIcon as Info } from '@phosphor-icons/react';

export function UnavailableRoute() {
  return (
    <section className="panel empty-state">
      <Info size={28} />
      <strong>能力模块尚未接入真实数据</strong>
      <p>虚拟演示数据已清理。后续接入经过授权的真实数据后，本入口将重新开放。</p>
    </section>
  );
}
