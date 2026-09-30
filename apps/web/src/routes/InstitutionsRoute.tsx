import { KnowledgeCatalog } from '../features/catalog/KnowledgeCatalog';
import { InstitutionDetail } from '../features/catalog/InstitutionDetail';
import { useParams } from 'react-router-dom';

export function InstitutionsRoute() {
  const { objectId } = useParams();
  if (objectId) return <InstitutionDetail objectId={objectId} />;
  return <KnowledgeCatalog
    title="机构字典"
    description="查询学校、学院、附属机构和部门，查看机构层级与当前关联记录。"
    searchPlaceholder="机构、学院或部门名称"
    kind="institutions"
    showTypeFilter={false}
    types={[
      { id: 'organization', label: '机构' },
      { id: 'department', label: '学院与部门' },
    ]}
  />;
}
