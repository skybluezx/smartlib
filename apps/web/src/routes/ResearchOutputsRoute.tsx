import { KnowledgeCatalog } from '../features/catalog/KnowledgeCatalog';
import { ResearchOutputDetail } from '../features/catalog/ResearchOutputDetail';
import { researchOutputTypes } from '../features/catalog/knowledgeSemantics';
import { useParams } from 'react-router-dom';

export function ResearchOutputsRoute() {
  const { objectId } = useParams();
  if (objectId) return <ResearchOutputDetail objectId={objectId} />;
  return <KnowledgeCatalog
    title="科研成果"
    description="查找并浏览已进入权威业务库的具体论文、项目、专利与数据集；资助计划等分类节点仅用于数据组织和图谱汇聚。"
    searchPlaceholder="成果题名、DOI、PMID、项目或关键词"
    kind="outputs"
    types={researchOutputTypes}
  />;
}
