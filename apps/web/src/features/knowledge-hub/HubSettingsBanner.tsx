import { useQuery } from '@tanstack/react-query';
import { Information } from '@carbon/icons-react';
import { hubRequest, type HubTable } from './hubApi';

/** Public workbench text only; infrastructure secrets are never requested here. */
export function HubSettingsBanner() {
  const settings = useQuery({
    queryKey: ['hub', 'settings', 'banner'],
    queryFn: () => hubRequest<HubTable>('/workbench/settings?page_size=100'),
  });
  const read = (code: string) => {
    const value = settings.data?.items.find(row => row.code === code)?.value;
    return typeof value === 'string' ? value : '';
  };
  const name = read('library_name');
  const notice = read('workbench_notice');
  const contact = read('service_contact');
  if (!name && !notice && !contact) return null;
  return <aside className="kh-workbench-banner" aria-label="图书馆工作台信息">
    <Information size={18} aria-hidden="true" />
    <div>{name && <strong>{name}</strong>}{notice && <p>{notice}</p>}
      {contact && <small>服务联系：{contact}</small>}
    </div>
  </aside>;
}
