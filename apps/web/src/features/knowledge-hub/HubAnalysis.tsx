import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Select, SelectItem, InlineLoading } from '@carbon/react';
import { Notice } from '../../shared/components/Notice';
import { hubRequest } from './hubApi';
import { HubHeading, HubNote } from './HubWorkspace';
interface LibraryAnalysis {metrics:{metric_code:string;metric_name:string;unit:string;records:number}[];items:{period:string;organization:string;value:number;unit:string;source_reference:string}[];note:string}
export function HubAnalysis(){
 const [code,setCode]=useState('');const [organization,setOrganization]=useState('');
 const data=useQuery({queryKey:['hub','library-analysis',code],queryFn:()=>hubRequest<LibraryAnalysis>(`/library-analysis?metric_code=${encodeURIComponent(code)}`)});
 const organizations=[...new Set(data.data?.items.map(row=>row.organization)??[])];
 const rows=data.data?.items.filter(row=>!organization||row.organization===organization)??[];
 const maximum=Math.max(0,...rows.map(row=>row.value));
 return <div className="kh-page"><HubHeading title="数据分析与服务" description="从共享数据出发，查看科研结构、馆务趋势与数据质量，保留统计范围和证据。"/>
  <section className="kh-analysis-links"><Link to="/knowledge-hub/library"><strong>馆务业务分析</strong><span>25 类工作表、年度记录、人次覆盖与业务明细</span><b>进入馆务工作台 →</b></Link><Link to="/graph-analytics"><strong>科研与知识图谱分析</strong><span>论文、期刊、基金、研究方向、学者及机构合作</span><b>进入分析 →</b></Link><Link to="/knowledge-hub/governance"><strong>数据质量分析</strong><span>核验任务、完整性检查和质量问题处理</span><b>查看质量 →</b></Link></section>
  <section className="kh-section"><div className="kh-section-heading"><div><h2>馆务月度趋势</h2><p>已登记的月度汇总值，按机构分别展示。</p></div><Link to="/knowledge-hub/library-metrics">维护月度指标 →</Link></div>
   <div className="kh-analysis-filters"><Select id="hub-analysis-metric" labelText="选择指标" value={code} onChange={e=>{setCode(e.target.value);setOrganization('');}}><SelectItem value="" text="请选择已登记指标"/>{data.data?.metrics.map(m=><SelectItem key={m.metric_code} value={m.metric_code} text={`${m.metric_name}（${m.unit}）`}/>)}</Select><Select id="hub-analysis-organization" labelText="选择机构" value={organization} onChange={e=>setOrganization(e.target.value)}><SelectItem value="" text="分别显示全部机构"/>{organizations.map(o=><SelectItem key={o} value={o} text={o}/>)}</Select></div>
   <HubNote>{data.data?.note??'不同指标不合并统计，缺少记录不视为零。'}</HubNote>
   {data.isFetching&&<InlineLoading description="正在读取馆务指标"/>}{data.error&&<Notice kind="error" title="读取失败" subtitle={data.error.message}/>}
   {!rows.length&&!data.isFetching&&<div className="kh-empty"><strong>{code?'当前指标尚无可见记录':'选择指标后查看月度变化'}</strong><p>此处查看月度汇总指标；业务事项与模拟演示请进入馆务数据管理。</p></div>}
   <div className="kh-library-chart" role="region" tabIndex={0} aria-label="馆务月度记录与来源，可滚动">{rows.map(row=><article key={`${row.period}-${row.organization}`}><div><strong>{row.period.slice(0,7)} · {row.organization}</strong><small>{row.source_reference}</small></div><span className="kh-library-track"><i style={{width:`${maximum?row.value/maximum*100:0}%`}}/></span><b>{row.value.toLocaleString('zh-CN')} {row.unit}</b></article>)}</div>
  </section>
 </div>;
}
