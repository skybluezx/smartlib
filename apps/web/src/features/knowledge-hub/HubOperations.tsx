import { useQuery } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { Button, InlineLoading } from '@carbon/react';
import { Renew } from '@carbon/icons-react';
import { getKnowledgeHubOverviewView } from '../../shared/api/smartlib';
import { Notice } from '../../shared/components/Notice';
import { HubHeading, HubNote } from './HubWorkspace';
export function HubOperations(){
 const graph=useLocation().pathname.endsWith('/graph');
 const data=useQuery({queryKey:['knowledge-hub-overview'],queryFn:getKnowledgeHubOverviewView});
 return <div className="kh-page"><HubHeading title={graph?'知识图谱运行':'搜索索引运行'} description="查看当前运行状态、业务读取后端和待派发事件，保留权威事实与派生存储的边界。"><Button kind="tertiary" renderIcon={Renew} onClick={()=>void data.refetch()}>刷新状态</Button></HubHeading>
 {data.isPending?<InlineLoading description="正在检查运行态势"/>:data.error?<Notice kind="error" title="状态读取失败" subtitle={data.error.message}/>:<>
  <div className="kh-metrics"><article><span>当前可见知识对象</span><strong>{Object.values(data.data.entity_counts).reduce((a,b)=>a+b,0)}</strong><small>按总览已统计对象类型合计</small></article><article><span>待派发事件</span><strong>{data.data.unpublished_events}</strong><small>不等同于两边数据完整对账</small></article><article><span>最近检查</span><strong className="kh-metric-time">{new Date(data.data.generated_at).toLocaleTimeString('zh-CN')}</strong><small>刷新可重新检查</small></article></div>
  <section className="kh-section"><h2>服务状态</h2><div className="kh-service-list">{data.data.services.filter(s=>s.service==='postgresql'||s.service.includes(graph?'graph':'search')).map(s=><article key={s.service}><span className={`kh-service-dot ${s.state==='available'?'available':''}`}/><div><strong>{s.service}</strong><span>{s.purpose}</span></div><div><b>{s.state==='available'?'可用':'不可用'}</b><small>{s.active_backend?'当前读取后端':s.detail}</small></div></article>)}</div></section>
  <HubNote>运行可用、事件派发完成与内容完全一致是不同检查。此页不执行全量重建或删除投影；需要重建时应先备份并单独确认。</HubNote>
  <div className="kh-shortcuts"><Link to={graph?'/graph-analytics':'/'}>{graph?'进入图谱分析':'进入搜索与发现'} →</Link><Link to="/knowledge-hub/history">查看版本与追溯 →</Link><Link to="/knowledge-hub/jobs">查看导入任务 →</Link></div>
 </>}
 </div>;
}
