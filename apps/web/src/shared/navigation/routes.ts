import {
  ArrowsLeftRightIcon as ArrowsLeftRight,
  DatabaseIcon as Database,
  BriefcaseIcon as Briefcase,
  ChartLineUpIcon as ChartLineUp,
  CheckSquareIcon as CheckSquare,
  FileTextIcon as FileText,
  HouseIcon as House,
  IdentificationCardIcon as IdentificationCard,
  MapTrifoldIcon as MapTrifold,
  PackageIcon as Package,
  PathIcon as Path,
  RocketLaunchIcon as RocketLaunch,
  LifebuoyIcon as Lifebuoy,
  UserFocusIcon as UserFocus,
  UsersThreeIcon as UsersThree,
  UsersIcon as Users,
  type Icon,
} from '@phosphor-icons/react';

export const roles = ['学校领导', '人事与科研部门', '学院与学科管理', '学者个人', '图书馆知识服务'] as const;
export type RoleId = typeof roles[number];

export type RouteId =
  | 'overview'
  | 'scholars'
  | 'compare'
  | 'disciplines'
  | 'recruitment'
  | 'evaluation'
  | 'teams'
  | 'researchManagement'
  | 'cultivation'
  | 'resources'
  | 'resourcePackages'
  | 'resourceServices'
  | 'transfer'
  | 'myProfile'
  | 'corrections'
  | 'reports';

export type NavigationGroup = 'primary' | 'business' | 'workspace';

export interface NavigationItem {
  id: RouteId;
  path: string;
  label: string;
  title: string;
  subtitle: string;
  icon: Icon;
  color?: string;
  group: NavigationGroup;
}

interface RoleNavigationItem {
  id: RouteId;
  group: NavigationGroup;
  label?: string;
  title?: string;
  subtitle?: string;
}

export interface RoleNavigation {
  home: RouteId;
  scope: string;
  groupLabels: Record<NavigationGroup, string>;
  items: RoleNavigationItem[];
}

export const navigationItems: NavigationItem[] = [
  { id: 'overview', path: '/', label: '工作台', title: '学者星图', subtitle: '科研人才数据画像与智能洞察', icon: House, group: 'primary' },
  { id: 'scholars', path: '/scholars', label: '人才发现', title: '人才发现', subtitle: '检索学者并查看事实画像与知识网络', icon: Users, color: 'purple', group: 'primary' },
  { id: 'compare', path: '/compare', label: '人才比较', title: '人才比较', subtitle: '在统一口径下比较画像、趋势与结构', icon: ArrowsLeftRight, color: 'purple', group: 'primary' },
  { id: 'disciplines', path: '/disciplines', label: '学科人才地图', title: '学科人才地图', subtitle: '观察人才结构、方向分布和交叉联系', icon: MapTrifold, color: 'purple', group: 'primary' },
  { id: 'recruitment', path: '/recruitment', label: '人才引进', title: '人才引进', subtitle: '形成候选人才分析并支撑业务确认', icon: UserFocus, color: 'purple', group: 'business' },
  { id: 'evaluation', path: '/evaluation', label: '人才评价', title: '人才评价', subtitle: '按任务组织多维材料、比较范围和依据', icon: CheckSquare, color: 'purple', group: 'business' },
  { id: 'teams', path: '/teams', label: '团队组建', title: '团队组建', subtitle: '按研究主题发现互补人才与关系路径', icon: UsersThree, color: 'purple', group: 'business' },
  { id: 'researchManagement', path: '/research-management', label: '科研管理', title: '科研管理', subtitle: '查询人才与成果、监测趋势并准备材料', icon: ChartLineUp, color: 'purple', group: 'business' },
  { id: 'cultivation', path: '/cultivation', label: '人才培育', title: '人才培育', subtitle: '跟踪发展变化并配置培养与科研支持', icon: RocketLaunch, color: 'purple', group: 'business' },
  { id: 'resources', path: '/resources', label: '资源发现', title: '资源发现', subtitle: '统一检索数据库、期刊、图书、论文、数据集与开放资源', icon: Database, color: 'purple', group: 'business' },
  { id: 'resourcePackages', path: '/resource-packages', label: '专题资源', title: '专题资源包', subtitle: '围绕学者、方向、团队和科研任务组织资源', icon: Package, color: 'purple', group: 'business' },
  { id: 'resourceServices', path: '/resource-services', label: '知识服务', title: '知识服务任务', subtitle: '申请、交付并跟踪检索、证据和科研支持服务', icon: Lifebuoy, color: 'purple', group: 'business' },
  { id: 'transfer', path: '/transfer', label: '转化线索', title: '科技转化与临床对接', subtitle: '连接团队能力、科研成果和实际需求', icon: Path, color: 'purple', group: 'business' },
  { id: 'myProfile', path: '/my-profile', label: '我的画像', title: '我的画像', subtitle: '核对学术档案、影响信息与研究方向', icon: IdentificationCard, color: 'purple', group: 'workspace' },
  { id: 'corrections', path: '/corrections', label: '纠错与确认', title: '纠错与确认', subtitle: '提交、核验并跟踪身份、成果和方向问题', icon: Briefcase, color: 'purple', group: 'workspace' },
  { id: 'reports', path: '/reports', label: '报告中心', title: '报告中心', subtitle: '生成、管理并导出带口径和来源的材料', icon: FileText, color: 'purple', group: 'workspace' },
];

export const routeById = Object.fromEntries(navigationItems.map((item) => [item.id, item])) as Record<RouteId, NavigationItem>;

export const roleNavigation: Record<RoleId, RoleNavigation> = {
  学校领导: {
    home: 'overview', scope: '全校数据视图',
    groupLabels: { primary: '决策视图', business: '重点工作', workspace: '决策材料' },
    items: [
      { id: 'overview', group: 'primary', label: '决策总览', title: '决策总览', subtitle: '全校人才结构、科研态势与重点事项' },
      { id: 'scholars', group: 'primary', label: '人才全景', title: '人才全景', subtitle: '查看全校人才结构并逐级追溯学者事实' },
      { id: 'disciplines', group: 'primary', label: '学科人才', title: '学科人才', subtitle: '观察学科人才分布、方向结构和交叉联系' },
      { id: 'researchManagement', group: 'primary', label: '科研态势', title: '科研态势', subtitle: '监测科研人才、成果与合作变化' },
      { id: 'resources', group: 'primary', label: '资源保障', title: '资源保障', subtitle: '查看电子资源覆盖、使用与科研服务情况' },
      { id: 'recruitment', group: 'business', label: '重点人才', title: '重点人才工作', subtitle: '查看引进任务、候选分析与复核进度' },
      { id: 'cultivation', group: 'business', label: '人才培育' },
      { id: 'teams', group: 'business', label: '团队布局', title: '团队布局', subtitle: '查看重点方向团队结构和能力覆盖' },
      { id: 'transfer', group: 'business', label: '转化线索', title: '转化线索', subtitle: '查看团队、成果与实际需求的候选联系' },
      { id: 'reports', group: 'workspace', label: '专题报告', title: '专题报告', subtitle: '查看人才、学科和科研专题材料' },
    ],
  },
  人事与科研部门: {
    home: 'overview', scope: '职能部门业务范围',
    groupLabels: { primary: '人才洞察', business: '业务办理', workspace: '工作管理' },
    items: [
      { id: 'overview', group: 'primary', label: '业务工作台', title: '业务工作台', subtitle: '待办、复核材料与进行中任务' },
      { id: 'scholars', group: 'primary', label: '人才库', title: '人才库', subtitle: '检索校内外学者并建立业务对象' },
      { id: 'compare', group: 'primary' },
      { id: 'recruitment', group: 'business' }, { id: 'evaluation', group: 'business' },
      { id: 'cultivation', group: 'business' }, { id: 'researchManagement', group: 'business' },
      { id: 'resources', group: 'business', label: '科研资源', title: '科研资源', subtitle: '按人才与科研任务发现可用学术资源' },
      { id: 'teams', group: 'business' }, { id: 'transfer', group: 'business' },
      { id: 'corrections', group: 'workspace', label: '业务确认', title: '业务确认', subtitle: '核验画像问题、事实归属和候选关系' },
      { id: 'reports', group: 'workspace' },
    ],
  },
  学院与学科管理: {
    home: 'overview', scope: '基础医学院',
    groupLabels: { primary: '本单位人才', business: '协同与培育', workspace: '材料与反馈' },
    items: [
      { id: 'overview', group: 'primary', label: '本单位总览', title: '本单位总览', subtitle: '本单位人才、方向、团队和待办事项' },
      { id: 'disciplines', group: 'primary', label: '人才地图', title: '本单位人才地图', subtitle: '查看人才层次、方向分布与骨干结构' },
      { id: 'scholars', group: 'primary', label: '本单位人才', title: '本单位人才', subtitle: '检索本单位学者并查看完整学术档案' },
      { id: 'resources', group: 'primary', label: '学科资源', title: '本单位学科资源', subtitle: '查看与本单位方向、团队和任务相关的资源' },
      { id: 'compare', group: 'primary' },
      { id: 'teams', group: 'business', label: '团队与合作', title: '团队与合作', subtitle: '发现跨团队联系并组织候选团队' },
      { id: 'cultivation', group: 'business' }, { id: 'resourcePackages', group: 'business', label: '专题资源包' }, { id: 'transfer', group: 'business' },
      { id: 'reports', group: 'workspace', label: '材料与报告', title: '材料与报告', subtitle: '准备学科人才清单、报告和任务材料' },
      { id: 'corrections', group: 'workspace', label: '数据核验', title: '数据核验', subtitle: '处理本单位画像、成果和方向问题' },
    ],
  },
  学者个人: {
    home: 'myProfile', scope: '当前登录学者',
    groupLabels: { primary: '个人空间', business: '科研协作', workspace: '我的事务' },
    items: [
      { id: 'myProfile', group: 'primary' },
      { id: 'teams', group: 'business', label: '合作发现', title: '合作发现', subtitle: '按研究主题寻找互补学者和关系路径' },
      { id: 'resources', group: 'business', label: '资源发现', title: '资源发现', subtitle: '检索本校可访问的数据库、全文与开放资源' },
      { id: 'resourcePackages', group: 'business', label: '专题资源', title: '我的专题资源', subtitle: '获取与研究方向和科研任务相关的资源包' },
      { id: 'resourceServices', group: 'business', label: '服务申请', title: '我的知识服务', subtitle: '申请检索、证据整理、培训和人工学科服务' },
      { id: 'transfer', group: 'business', label: '成果应用线索', title: '成果应用线索', subtitle: '查看本人团队成果与实际需求的候选联系' },
      { id: 'corrections', group: 'workspace', label: '我的反馈', title: '我的反馈', subtitle: '提交并跟踪学术档案和画像问题' },
      { id: 'reports', group: 'workspace', label: '我的材料', title: '我的材料', subtitle: '管理个人画像快照和已生成材料' },
    ],
  },
  图书馆知识服务: {
    home: 'overview', scope: '图书馆服务范围',
    groupLabels: { primary: '服务对象', business: '知识服务', workspace: '质量与运营' },
    items: [
      { id: 'overview', group: 'primary', label: '服务工作台', title: '服务工作台', subtitle: '服务任务、数据核验与资源组织进展' },
      { id: 'resources', group: 'primary', label: '电子资源中心', title: '电子资源中心', subtitle: '管理并连接数据库、电子期刊、图书、论文、数据集和自建资源' },
      { id: 'scholars', group: 'primary', label: '服务对象发现', title: '服务对象发现', subtitle: '按方向、阶段和任务发现学者与团队' },
      { id: 'disciplines', group: 'primary', label: '学科服务对象', title: '学科服务对象', subtitle: '观察学科人才、方向和资源支持需求' },
      { id: 'resourcePackages', group: 'business', label: '专题资源组织', title: '专题资源组织', subtitle: '围绕学者、方向、团队和任务建设资源包' },
      { id: 'resourceServices', group: 'business', label: '知识服务任务', title: '知识服务任务', subtitle: '受理、分派、交付并回访科研知识服务' },
      { id: 'teams', group: 'business', label: '团队服务', title: '团队服务', subtitle: '识别团队能力、合作关系和知识服务需求' },
      { id: 'corrections', group: 'workspace', label: '画像核验', title: '画像与数据核验', subtitle: '处理身份、成果、方向和来源证据问题' },
      { id: 'reports', group: 'workspace', label: '服务报告', title: '服务报告', subtitle: '汇总服务对象、任务、资源和反馈' },
    ],
  },
};

export function navigationForRole(role: RoleId): NavigationItem[] {
  return roleNavigation[role].items.map((roleItem) => ({ ...routeById[roleItem.id], ...roleItem }));
}

export function routeForPath(pathname: string, role: RoleId = '学校领导'): NavigationItem {
  const base = navigationItems.find((item) => item.path === pathname) ?? routeById[roleNavigation[role].home];
  return navigationForRole(role).find((item) => item.id === base.id) ?? base;
}
