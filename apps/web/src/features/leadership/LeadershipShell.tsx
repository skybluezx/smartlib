import './leadership.css';
import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, Outlet, useLocation, useOutletContext, useSearchParams } from 'react-router-dom';
import { Button, ComboBox, Header, HeaderGlobalAction, HeaderGlobalBar, HeaderMenuButton, HeaderName, InlineLoading, InlineNotification, SideNav, SideNavItems, SideNavLink, SkipToContent, Tag, TextInput, Theme } from '@carbon/react';
import { Home, Information, Renew } from '@carbon/icons-react';
import { getGraphAnalysisScopeOptionsView, listCustomGraphScopesView } from '../../shared/api/smartlib';
import { leaderPages } from './catalog';
import { emptyScope, leaderRequest, readScope, scopeParams, type LeaderScope, type Session, type Summary } from './api';
interface LeaderContext {scope:LeaderScope;summary:Summary;session:Session;search:string}
export const useLeader=()=>useOutletContext<LeaderContext>();
export function LeadershipShell(){
 const session=useQuery({queryKey:['leader-session'],queryFn:({signal})=>leaderRequest<Session>('/session',undefined,signal),retry:false});
 return <div className="ld-root">{session.isPending?<div className="ld-boundary"><InlineLoading description="核验工作台访问权限…"/></div>:session.isError?<main className="ld-boundary"><h1>学校领导工作台</h1><InlineNotification kind="error" title="暂时无法进入" subtitle={session.error.message} hideCloseButton/><Link to="/">返回学者星图</Link><Button kind="ghost" onClick={()=>void session.refetch()}>重试</Button></main>:<LeaderContent session={session.data}/>}</div>;
}
function LeaderContent({session}:{session:Session}){
 const queryClient=useQueryClient();
 const refresh=()=>void queryClient.invalidateQueries({predicate:q=>String(q.queryKey[0]).startsWith('leader-')});
 const location=useLocation();const [params,setParams]=useSearchParams();const scope=readScope(params);const search=scopeParams(scope).toString();
 const [open,setOpen]=useState(()=>window.innerWidth>=1056);
 const page=leaderPages.find(p=>location.pathname.replace(/\/$/,'')==='/leadership'+(p.path?'/'+p.path:''))??leaderPages[0];
 const summary=useQuery({queryKey:['leader-summary',scope],queryFn:({signal})=>leaderRequest<Summary>('/summary',scope,signal),staleTime:60000});
 useEffect(()=>{document.title=`${page.label} · 学校领导 · 学者星图`;},[page.label]);
 return <><Theme theme="g100"><Header aria-label="学校领导工作台"><SkipToContent/><HeaderMenuButton aria-label={open?'关闭导航':'打开导航'} isActive={open} onClick={()=>setOpen(!open)}/><HeaderName prefix="SmartLib" href="/">学者星图</HeaderName><span className="ld-header-role">学校领导工作台</span><HeaderGlobalBar><HeaderGlobalAction aria-label="返回学者星图" onClick={()=>{window.location.href='/';}}><Home size={20}/></HeaderGlobalAction></HeaderGlobalBar></Header></Theme>
 <Theme theme="white"><SideNav expanded={open} isPersistent={false} aria-label="学校领导导航" onOverlayClick={()=>setOpen(false)}><SideNavItems>{['决策视图','重点工作','决策材料'].map(group=><li key={group} className="ld-nav-group"><h2>{group}</h2><ul>{leaderPages.filter(p=>p.group===group).map(p=><SideNavLink key={p.path} as={Link} to={'/leadership'+(p.path?'/'+p.path:'')+(search?'?'+search:'')} isActive={page.path===p.path} onClick={()=>{if(window.innerWidth<1056)setOpen(false);}}>{p.label}</SideNavLink>)}</ul></li>)}</SideNavItems></SideNav></Theme>
 <main id="main-content" className={`ld-main ${open?'ld-nav-visible':''}`}>
 <header className="ld-heading"><div><span className="ld-eyebrow">学校领导 / {page.group}</span><h1>{page.label}</h1><p>{page.description}</p></div><div className="ld-heading-actions"><Tag type={session.role_verified?'teal':'cool-gray'}>{session.role_verified?'岗位授权视图':'免登录预览'}</Tag><Button kind="tertiary" size="sm" renderIcon={Renew} onClick={refresh}>刷新数据</Button></div></header>
 {!session.role_verified&&<p className="ld-auth-note">本轮暂不接入登录，可直接查看领导工作台；数据仍受现有后台权限约束。</p>}
 <ScopeControls key={search} scope={scope} onApply={next=>setParams(scopeParams(next))}/>
 {summary.isPending?<section className="ld-section"><InlineLoading description="正在按共同范围汇总数据…"/></section>:summary.isError?<section className="ld-section"><InlineNotification kind="error" title="范围数据读取失败" subtitle={summary.error.message} hideCloseButton/><Button kind="ghost" onClick={()=>void summary.refetch()}>重试</Button></section>:<>
 <div className="ld-scope-summary"><span><strong>{summary.data.scope_name}</strong> · {summary.data.coverage.publications} 篇论文</span><span>计算时间 {new Date(summary.data.generated_at).toLocaleString('zh-CN')}</span></div>
 <Note>{summary.data.boundary} 年份筛选按论文发表年份；机构筛选按论文署名关系，包含下级机构。</Note>
 <Outlet context={{scope,summary:summary.data,session,search} satisfies LeaderContext}/></>}
 </main></>;
}
function ScopeControls({scope,onApply}:{scope:LeaderScope;onApply:(s:LeaderScope)=>void}){
 const [draft,setDraft]=useState(scope);const [start,setStart]=useState(scope.start_year?.toString()??'');const [end,setEnd]=useState(scope.end_year?.toString()??'');const [error,setError]=useState('');
 const options=useQuery({queryKey:['scholar-graph-analysis-scope-options'],queryFn:({signal})=>getGraphAnalysisScopeOptionsView(signal),staleTime:300000});
 const saved=useQuery({queryKey:['custom-graph-scopes'],queryFn:listCustomGraphScopesView});
 const apply=()=>{const a=start===''?null:Number(start),b=end===''?null:Number(end);if([a,b].some(v=>v!==null&&(!Number.isInteger(v)||v<1500||v>2200))||(a!==null&&b!==null&&a>b)){setError('请填写有效年份，开始年份不能晚于结束年份。');return;}setError('');onApply({...draft,start_year:a,end_year:b});};
 return <section className="ld-scope"><div className="ld-scope-fields"><TextInput id="leader-start" labelText="开始年份" type="number" value={start} placeholder="不限" onChange={e=>setStart(e.target.value)}/><TextInput id="leader-end" labelText="结束年份" type="number" value={end} placeholder="不限" onChange={e=>setEnd(e.target.value)}/>
 <ComboBox id="leader-org" titleText="署名机构范围" placeholder="全部机构，可输入检索" items={options.data?.organizations??[]} itemToString={i=>i?.name??''} selectedItem={options.data?.organizations?.find(i=>i.object_id===draft.organization_id)??null} onChange={({selectedItem})=>setDraft({...draft,organization_id:selectedItem?.object_id??null})}/>
 <ComboBox id="leader-custom" titleText="已保存的自定义范围" placeholder="全部可访问论文" items={saved.data??[]} itemToString={i=>i?.name??''} selectedItem={saved.data?.find(i=>i.scope_id===draft.custom_scope_id)??null} onChange={({selectedItem})=>setDraft({...draft,custom_scope_id:selectedItem?.scope_id??null})}/>
 <Button size="md" onClick={apply}>应用范围</Button><Button kind="ghost" size="md" onClick={()=>onApply(emptyScope)}>重置</Button></div>
 {error&&<p role="alert" className="ld-error">{error}</p>}{(options.isError||saved.isError)&&<p role="alert">部分范围选项读取失败，已有条件仍保留。<button className="ld-link-button" onClick={()=>{void options.refetch();void saved.refetch();}}>重试</button></p>}
 <p className="ld-hint">范围在决策视图间保持一致；事项台账、资源登记和历史报告有各自范围，不随年份筛选隐藏。</p></section>;
}
export function Note({children}:{children:React.ReactNode}){return <div className="ld-note"><Information size={18}/><span>{children}</span></div>;}
