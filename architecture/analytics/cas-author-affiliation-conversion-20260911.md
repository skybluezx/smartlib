# 中科院署名转换为作者机构关系

2026-09-11。替代此前 cas-affiliation-repair-20260911.md 中合并论文机构来源的修复方式。

## 权威模型

仅使用 person.affiliated_with，subject 为具体作者、object 为机构、context_object_id 为对应论文；publication_relation_provenance 对应具体 publication_authorship。原论文直接关联机构的模型已停用，不允许新建。

## 数据转换

31条旧记录的 authors 数组包含135个作者—论文—机构对应。逐项核对：均有现存作者署名标识、匹配的父机构署名关系，而且该作者的 raw_affiliation 明确包含目标下级机构名称。没有根据同篇出现而向所有作者分配机构，没有新增独立全文核验结论。

事务新增135条 pending 作者机构关系、135条署名来源映射和1402条去重证据链接。attributes.assignments 保存旧关系与父级作者关系编号；31条旧关系标为 superseded，保留原记录和审计历史。关系注册表中 publication.affiliated_with 标记 retired，replacement_predicate 为 person.affiliated_with。没有关闭任何契约、证据或版本约束。

可重复执行的受控SQL：apps/platform-api/scripts/convert_cas_paper_affiliations_20260911.sql。任何作者、论文或原始署名对应不匹配都会中止事务。

## 代码清理

- 删除 load_publication_institution_rows 及机构合作合并分支。
- 删除分析范围选项和论文范围查询中的 publication.affiliated_with 分支。
- 将相关测试改为作者机构语义，去掉兼容查询测试。
- 运行时代码及前端测试不再引用旧关系类型；历史数据库迁移、审计文件与退役记录保留，不改写迁移历史。
- “下属单位未明确”显示保留：它由作者的一级机构署名产生，不依赖旧论文机构关系。

## 验证

34项后端测试通过；11项关系图前端测试通过。实际接口复现两个一级展开、大医分成两个组合，中科院7个下级机构及26篇去重论文保持完整；分析快照独立复算一致。

定向同步166条新旧关系事件。直接回读 HugeGraph：135条新作者机构边存在，31条旧论文机构边不存在。PostgreSQL旧记录保留历史状态，不再参与分析。

## 全面复核（2026-09-11）

- 全仓扫描：业务源码与测试无旧谓词或已删除加载器；残留仅历史迁移、审计文档、转换及历史导入脚本。
- 当前 PostgreSQL：旧关系31条，全部 superseded；analysis_relation 中0条；graph_relation_json 对全部旧关系均返回空，重建不会重新投影。
- HugeGraph 按 predicate 全局检索：0条旧边（不限于此前31个ID）。
- 已保存 custom_graph_analysis_scope.graph_query：0条引用旧谓词。
- 数据库视图及函数定义：没有旧谓词专用兼容分支；别名表已由V40移除。
- person.affiliated_with 主体类型检查：非 person 记录0条。
- 补上V69正式停用迁移，Flyway应用成功。若其他数据库仍有未处理的当前旧关系，迁移将中止并要求证据支持的转换，不自动给全部作者分配机构。
- 两份旧导入脚本 create_secondary.sql / create_hias.sql 增加执行前异常拦截，保留历史内容但不可重放。
- 历史V30/V31迁移不改写，以保留迁移校验和；从头建库在V69结束时停用旧谓词。
