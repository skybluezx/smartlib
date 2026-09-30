export const leaderPages=[
 {path:'',label:'决策总览',group:'决策视图',description:'从当前可用数据观察科研基础、结构变化与需要跟进的事项。'},
 {path:'talent',label:'人才全景',group:'决策视图',description:'查看论文关联学者及其成果与署名机构，逐项追溯事实。'},
 {path:'disciplines',label:'学科人才',group:'决策视图',description:'查看研究方向积累、关联人才和交叉研究基础。'},
 {path:'research',label:'科研态势',group:'决策视图',description:'结合年度产出、期刊表现、引文指标与基金来源观察科研样本。'},
 {path:'resources',label:'资源保障',group:'决策视图',description:'检查已登记的数据资源及许可依据，明确资源配置还缺哪些证据。'},
 {path:'recruitment',label:'重点人才',group:'重点工作',description:'围绕明确的人才工作问题组织事实材料，跟踪部门核实与专家讨论。'},
 {path:'cultivation',label:'人才培育',group:'重点工作',description:'将研究基础与支持措施相连接，记录目标、复盘时间和后续变化。'},
 {path:'teams',label:'团队布局',group:'重点工作',description:'从完整论文范围的合作结构观察合作群体、关键连接和方向支撑。'},
 {path:'transfer',label:'转化线索',group:'重点工作',description:'围绕临床或产业问题整理成果依据，跟踪人工核实与对接进展。'},
 {path:'reports',label:'专题报告',group:'决策材料',description:'保存当前范围的科研简报，回看固定结果并导出带口径的材料。'},
] as const;
export const readiness=[
 ['科研论文与合作','当前样本可分析','论文、作者、署名机构和合作关系可下钻；不能外推全校完整成果。'],
 ['人事队伍结构','待接入人事数据','需在岗名册、有效期机构归属、岗位、职称及职业阶段，才能统计校内人才结构。'],
 ['历史申请与发展','待补充历史记录','需历年全部申请与完整成果；不据成功案例计算申报成功率。'],
 ['资源投入与使用','待接入投入使用数据','资源登记不等于订购覆盖；成本效益还需经费、使用、服务及许可记录。'],
 ['临床与产业转化','待核实需求与成果条件','需正式需求、知识产权、验证阶段和对接反馈，不将研究主题匹配写成可转化结论。'],
];
export const statusLabels={proposed:'待讨论',investigating:'核实中',tracking:'跟进中',closed:'已结束'};
