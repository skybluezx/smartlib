import { useDeferredValue, useRef, useState } from 'react';
import { Link, useOutletContext, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Add, Download, DocumentImport, Renew } from '@carbon/icons-react';
import { Button, InlineLoading, Modal, Pagination, Search, Select, SelectItem, TextArea, TextInput } from '@carbon/react';
import { HubHeading, HubNote } from './HubWorkspace';
import { hubRequest, downloadCsv } from './hubApi';
import { Notice } from '../../shared/components/Notice';
import type { KnowledgeHubOutletContext } from './KnowledgeHubShell';
import { type WorkCategory, type WorkOverview, type WorkRecord, type WorkBatch, modeName, timeText } from './libraryWorkTypes';
import { LibraryImport } from './LibraryImport';
import './libraryWork.css';
const api='/library-work';
const tabs=[['overview','业务总览'],['records','业务台账'],['imports','导入批次'],['catalog','字段目录']] as const;
const colors=['#0f62fe','#007d79','#8a3ffc','#a2191f','#005d5d','#6929c4'];

export function LibraryWork(){
 const [params,setParams]=useSearchParams(); const tab=tabs.some(t=>t[0]===params.get('view'))?(params.get('view')??'overview'):'overview';
 const mode=params.get('mode')==='demo'?'demo':'real';
 const {permissions}=useOutletContext<KnowledgeHubOutletContext>(); const writable=permissions.includes('knowledge_hub.manage');
 const [category,setCategory]=useState('');const [year,setYear]=useState('');const [department,setDepartment]=useState('');const [state,setState]=useState('active');const [q,setQ]=useState(''); const query=useDeferredValue(q);const [page,setPage]=useState(1);
 const [detailId,setDetailId]=useState<string|null>(null);const [editing,setEditing]=useState<WorkRecord|'new'|null>(null);const [importing,setImporting]=useState(false);const [batchId,setBatchId]=useState<string|null>(null);const [message,setMessage]=useState('');
 const cache=useQueryClient();const filters=new URLSearchParams({mode,category,department,q:query,state,...(year?{year}:{})});
 const catalog=useQuery({queryKey:['library-work','catalog'],queryFn:()=>hubRequest<WorkCategory[]>(api+'/catalog')});
 const overview=useQuery({queryKey:['library-work','overview',filters.toString()],queryFn:()=>hubRequest<WorkOverview>(api+'/overview?'+filters.toString())});
 const list=useQuery({queryKey:['library-work','records',filters.toString(),page],queryFn:()=>hubRequest<{items:WorkRecord[];total:number}>(api+'/records?'+filters.toString()+'&page='+String(page)),enabled:tab==='records'});
 const batches=useQuery({queryKey:['library-work','batches',mode],queryFn:()=>hubRequest<(Omit<WorkBatch,'errors'> & {errors:number})[]>(api+'/batches?mode='+mode),enabled:tab==='imports'});
 const detail=useQuery({queryKey:['library-work','record',detailId],queryFn:()=>hubRequest<WorkRecord>(api+'/records/'+(detailId??'')),enabled:detailId!==null});
 const refresh=()=>cache.invalidateQueries({queryKey:['library-work']});
 const navigate=(view:string)=>setParams(p=>{p.set('view',view);return p;});
 const reset=()=>{setCategory('');setYear('');setDepartment('');setQ('');setState('active');setPage(1);};
 const specs=catalog.data??[];const spec=(code:string)=>specs.find(s=>s.code===code);const stats=overview.data?.summary;
 const error=catalog.error??overview.error??(tab==='records'?list.error:null)??(tab==='imports'?batches.error:null);
 const finished=(text:string)=>{setMessage(text);void refresh();};
 return <div className="kh-page lw-page">
  <HubHeading title="馆务数据管理" description="从业务事项到年度回顾，保留工作记录、原始字段和每次修订的依据。">
   <Button kind="ghost" renderIcon={Renew} onClick={()=>void refresh()}>刷新</Button>
   {writable&&<><Button kind="tertiary" renderIcon={DocumentImport} onClick={()=>{setBatchId(null);setImporting(true);}}>导入工作表</Button><Button renderIcon={Add} disabled={!specs.length} onClick={()=>setEditing('new')}>登记事项</Button></>}
  </HubHeading>
  <div className="lw-context"><Select id="lw-mode" labelText="数据用途" value={mode} onChange={e=>{reset();setParams(p=>{p.set('mode',e.target.value);return p;});}}><SelectItem value="real" text="正式数据"/><SelectItem value="demo" text="模拟数据 · 仅供演示"/></Select><div><strong>{mode==='demo'?'正在查看模拟业务事项':'正式馆务台账'}</strong><p>{mode==='demo'?'独立生成的测试记录，不代表本馆真实业绩，不计入正式统计。':'原始文件尚需预检并由馆员确认导入；不会把演示记录转为真实业绩。'}</p></div><Link to="/knowledge-hub/library-metrics">月度指标台账 →</Link></div>
  <HubNote>按本人可见记录统计，暂不向学者星图或领导工作台发布明细。党务、人员等内部信息保留在本台账；不同业务的人次不去重，也不跨类型加总。</HubNote>
  {message&&<Notice kind="success" title={message} onCloseButtonClick={()=>setMessage('')}/>}
  {error&&<Notice kind="error" title="未能读取馆务数据" subtitle={error.message} actions={<Button kind="ghost" onClick={()=>void refresh()}>重试</Button>}/>}
  <nav className="lw-tabs" aria-label="馆务工作区">{tabs.map(([key,label])=><button key={key} type="button" aria-current={tab===key?'page':undefined} onClick={()=>navigate(key)}>{label}</button>)}</nav>
  {(tab==='overview'||tab==='records')&&<>
   <section className="lw-filters" aria-label="统计与台账共用筛选">
    <Select id="lw-category" labelText="业务类型" value={category} onChange={e=>{setCategory(e.target.value);setPage(1);}}><SelectItem value="" text="全部业务类型"/>{[...new Set(specs.map(s=>s.group))].map(group=><optgroup key={group} label={group}>{specs.filter(s=>s.group===group).map(s=><option key={s.code} value={s.code}>{s.name}</option>)}</optgroup>)}</Select>
    <Select id="lw-year" labelText="业务发生年份" value={year} onChange={e=>{setYear(e.target.value);setPage(1);}}><SelectItem value="" text="全部年份（含时间缺失）"/>{overview.data?.options.years?.map(y=><SelectItem key={y} value={String(y)} text={String(y)}/>)}</Select>
    <Select id="lw-dept" labelText="责任 / 相关单位（原表）" value={department} onChange={e=>{setDepartment(e.target.value);setPage(1);}}><SelectItem value="" text="全部单位或负责人"/>{overview.data?.options.departments?.map(d=><SelectItem key={d} value={d} text={d}/>)}</Select>
    <Select id="lw-state" labelText="记录状态" value={state} onChange={e=>{setState(e.target.value);setPage(1);}}><SelectItem value="active" text="有效记录"/><SelectItem value="withdrawn" text="已撤回"/><SelectItem value="all" text="全部状态"/></Select>
    <Search id="lw-search" labelText="搜索业务事项" placeholder="名称、原始字段关键词" value={q} onChange={e=>{setQ(e.target.value);setPage(1);}}/><Button size="sm" kind="ghost" onClick={reset}>重置筛选</Button>
   </section>
   {overview.isFetching&&<InlineLoading description="正在更新当前范围"/>}
   <section className="lw-stats" aria-label="当前筛选范围汇总">{[['业务事项',stats?.records,'按记录计数'],['已涉及业务类型',stats?.categories,`已配置 ${specs.length} 类工作表`],['时间未确定',stats?.unknown_dates,'不纳入按年统计'],['需补充或核对',stats?.needs_attention,'时间精度或参与人数待补全']].map(([label,value,note])=><div key={label}><span>{label}</span><strong>{value??'—'}</strong><small>{note}</small></div>)}</section>
  </>}
  {tab==='overview'&&<div className="lw-dashboard">
   <section className="lw-panel"><header><div><h2>业务分布</h2><p>按有效筛选范围计数，点击类型查看具体事项。</p></div></header>
    {!overview.isPending&&stats?.records===0&&<Empty mode={mode} onDemo={()=>setParams(p=>{p.set('mode','demo');return p;})}/>}
    <div className="lw-chart-list">{overview.data?.categories.map((c,i)=><button className="lw-bar-row" key={c.category} style={{'--fill':`${c.records/Math.max(1,stats?.records??0)*100}%`,'--bar-color':colors[i%colors.length]} as React.CSSProperties} onClick={()=>{setCategory(c.category);setPage(1);navigate('records');}}><span>{c.name}<small>{c.group}</small></span><strong>{c.records} <small>项</small></strong><span>{(c.records/Math.max(1,stats?.records??0)*100).toFixed(1)}%</span></button>)}</div>
   </section>
   <div className="lw-side"><section className="lw-panel"><h2>年度记录分布</h2><p>依据业务发生时间；年份缺失单列。</p><div className="lw-year-chart">{overview.data?.years.map(y=><button key={y.year??'unknown'} disabled={!y.year} onClick={()=>{if(y.year)setYear(String(y.year));setPage(1);navigate('records');}}><span>{y.year??'时间未确定'}</span><i style={{width:`${y.records/Math.max(1,...overview.data.years.map(v=>v.records))*100}%`}}/><strong>{y.records} 项</strong></button>)}</div></section>
    <section className="lw-panel"><h2>参与人次</h2><p>只在同一业务类型内汇总。覆盖不足时保留缺失，不能用作独立读者人数。</p><div className="lw-audience">{overview.data?.categories.filter(c=>c.audience_field).map(c=><div key={c.category}><span>{c.name}<small>{c.audience_field} · 可计算 {c.audience_covered}/{c.records} 项</small></span><strong>{c.audience_total??'未提供'}{c.audience_total!==null&&<small> 人次</small>}</strong></div>)}</div></section>
    <section className="lw-panel lw-guide"><h2>工作流</h2><ol><li>选择业务类型，登记或导入工作表。</li><li>检查原始字段、缺失提示与来源。</li><li>修订记录，按年度或业务分类回顾。</li></ol><Link to="/knowledge-hub/library?view=catalog">查看全部工作表字段 →</Link></section>
   </div>
  </div>}
  {tab==='records'&&<section className="kh-data-panel"><div className="kh-table-toolbar"><h2>业务事项 <small>· {modeName(mode)}</small></h2><Button kind="ghost" size="sm" renderIcon={Download} disabled={!list.data?.items.length} onClick={()=>downloadCsv('馆务事项-当前页.csv',[['数据用途','业务类型','事项名称','时间原值','责任或相关单位','记录状态'],...(list.data?.items??[]).map(r=>[modeName(r.mode),spec(r.category)?.name,r.title,r.fields[spec(r.category)?.date_field??''],r.department,r.state==='active'?'有效':'已撤回'])])}>导出当前页</Button></div>
   {list.isFetching&&<InlineLoading description="正在读取业务台账"/>}<div className="kh-table-scroll"><table><thead><tr><th>业务类型</th><th>事项名称</th><th>业务时间</th><th>责任 / 相关单位</th><th>记录情况</th><th>操作</th></tr></thead><tbody>{list.data?.items.map(r=><tr key={r.id}><td>{spec(r.category)?.name}</td><td className="lw-title-cell">{r.title}<small>{modeName(r.mode)} · 版本 {r.version}</small></td><td>{showValue(r.fields[spec(r.category)?.date_field??''])}</td><td>{r.department||'未提供'}</td><td>{r.state==='withdrawn'?'已撤回':r.warnings.length?'需补充或核对':'有效记录'}</td><td><Button kind="ghost" size="sm" onClick={()=>setDetailId(r.id)}>查看详情</Button>{writable&&<Button kind="ghost" size="sm" onClick={()=>setEditing(r)}>修订</Button>}</td></tr>)}</tbody></table></div>
   {!list.isPending&&!list.error&&!list.data.total&&<div className="kh-empty">当前条件下没有业务记录，可调整筛选或登记新事项。</div>}
   <Pagination page={page} pageSize={25} pageSizes={[25]} totalItems={list.data?.total??0} itemsPerPageText="每页" backwardText="上一页" forwardText="下一页" itemRangeText={(a,b,n)=>`第 ${a}–${b} 条，共 ${n} 条`} onChange={({page:p})=>setPage(p)}/>
  </section>}
  {tab==='imports'&&<section className="lw-panel"><h2>导入批次</h2><HubNote>显示最近 100 次预检与导入。预检 24 小时内可确认；有错误时整批不写入。重复提交同一批文件不会重复计数。</HubNote>{batches.isFetching&&<InlineLoading description="正在读取导入批次"/>}<div className="kh-table-scroll"><table><thead><tr><th>文件</th><th>用途</th><th>业务记录</th><th>预检错误 / 提示</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{batches.data?.map(b=><tr key={b.id}><td>{b.filename}</td><td>{modeName(b.mode)}</td><td>{b.count}</td><td>{b.errors} / {b.warning_count}</td><td>{b.state==='imported'?'已导入':'仅预检'}</td><td>{timeText(b.created_at)}</td><td><Button kind="ghost" size="sm" onClick={()=>{setBatchId(b.id);setImporting(true);}}>查看预检</Button></td></tr>)}</tbody></table></div>{!batches.isPending&&!batches.error&&!batches.data.length&&<div className="kh-empty">暂无此用途的导入批次。</div>}</section>}
  {tab==='catalog'&&<section className="lw-catalog"><header><h2>25 类馆务工作表</h2><p>来自所提供的原始工作表结构。模板仅包含字段，不含真实个人或业务内容。</p></header>{[...new Set(specs.map(s=>s.group))].map(group=><section key={group}><h3>{group}</h3><div className="lw-category-grid">{specs.filter(s=>s.group===group).map(s=><details key={s.code}><summary>{s.name}<small>{s.fields.length} 个字段</small></summary><p>{s.sensitive?'含人员及党务内部信息，仅本人可见。':'保留原表字段；空白值不自动推断。'}</p><dl><dt>事项标题</dt><dd>{s.title_field}</dd><dt>业务时间</dt><dd>{s.date_field}</dd></dl><div className="lw-field-tags">{s.fields.map(f=><span key={f}>{f}</span>)}</div><Button kind="ghost" size="sm" renderIcon={Download} onClick={()=>downloadCsv(`${s.name}.csv`,[s.fields])}>下载空白模板</Button></details>)}</div></section>)}</section>}
  {editing&&<WorkEditor record={editing} mode={mode} categories={specs} onClose={()=>setEditing(null)} onSaved={()=>{setEditing(null);finished('事项已保存，原始字段及修订依据已留档。');}}/>}
  {importing&&<LibraryImport mode={mode} batchId={batchId} categories={specs} writable={writable} onClose={()=>setImporting(false)} onSaved={(count,reused,importMode)=>{setImporting(false);reset();setParams(p=>{p.set('mode',importMode);p.set('view','records');return p;});finished(reused?'此文件已导入，未重复写入。':`已导入 ${count} 条${modeName(importMode)}记录。`);}}/>}
  {detailId&&<Modal open passiveModal size="lg" modalHeading="馆务事项详情" onRequestClose={()=>setDetailId(null)}>{detail.isPending?<InlineLoading description="读取事项"/>:detail.error?<Notice kind="error" title="读取失败" subtitle={detail.error.message}/>:<><div className="lw-detail-head"><h3>{detail.data.title}</h3><span>{modeName(detail.data.mode)} · {spec(detail.data.category)?.name} · 版本 {detail.data.version}</span></div><HubNote>来源：{detail.data.origin.file}{detail.data.origin.sheet&&` / ${detail.data.origin.sheet} / 第 ${detail.data.origin.row} 行`}。{detail.data.warnings.join('；')||'字段检查未发现时间或人次缺失。'}</HubNote><FieldList fields={detail.data.fields}/><h3>修订记录</h3>{detail.data.history?.map(h=><details className="lw-history" key={h.version}><summary>版本 {h.version} · {timeText(h.created_at)} · {h.reason}</summary><p>状态：{h.snapshot.state==='withdrawn'?'已撤回':'有效'}</p><FieldList fields={h.snapshot.fields}/></details>)}</>}</Modal>}
 </div>;
}
function Empty({mode,onDemo}:{mode:string;onDemo:()=>void}){return <div className="kh-empty"><strong>当前范围尚无{modeName(mode)}</strong><p>可上传原表完成预检后导入，也可先用模拟记录熟悉流程。</p>{mode==='real'&&<Button kind="tertiary" size="sm" onClick={onDemo}>查看已导入的模拟数据</Button>}</div>;}
function FieldList({fields}:{fields:Record<string,string>}){return <dl className="lw-fields">{Object.entries(fields).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v||'未提供'}</dd></div>)}</dl>;}
function WorkEditor({record,mode,categories,onClose,onSaved}:{record:WorkRecord|'new';mode:'real'|'demo';categories:WorkCategory[];onClose:()=>void;onSaved:()=>void}){
 const existing=record==='new'?null:record;const [category,setCategory]=useState(existing?.category??categories[0]?.code??'');const [fields,setFields]=useState<Record<string,string>>(existing?.fields??{});const [reason,setReason]=useState('');const [state,setState]=useState(existing?.state??'active');const form=useRef<HTMLFormElement>(null);const spec=categories.find(s=>s.code===category);
 const save=useMutation({mutationFn:()=>hubRequest(api+'/records'+(existing?`/${existing.id}/revision`:''),{category,fields,mode:existing?.mode??mode,reason,...(existing?{base_version:existing.version,state}:{})}),onSuccess:onSaved});
 if(!spec)return null;
 return <Modal open size="lg" modalHeading={existing?'修订业务事项':'登记业务事项'} primaryButtonText={save.isPending?'保存中':'保存事项'} secondaryButtonText="取消" primaryButtonDisabled={save.isPending} onRequestClose={()=>!save.isPending&&onClose()} onRequestSubmit={()=>{if(form.current?.reportValidity())save.mutate();}}><HubNote>{modeName(existing?.mode??mode)}。时间支持年、年月或完整日期；未知内容留空。撤回记录不再计入默认统计，历史版本保留。</HubNote><form ref={form} className="lw-editor" onSubmit={e=>{e.preventDefault();save.mutate();}}><Select id="lw-edit-category" labelText="业务类型" value={category} disabled={!!existing} onChange={e=>{setCategory(e.target.value);setFields({});}}>{categories.map(s=><SelectItem key={s.code} value={s.code} text={s.name}/>)}</Select>{existing&&<Select id="lw-edit-state" labelText="记录状态" value={state} onChange={e=>setState(e.target.value as 'active'|'withdrawn')}><SelectItem value="active" text="有效记录"/><SelectItem value="withdrawn" text="撤回（不删除历史）"/></Select>}<div className="lw-editor-grid">{spec.fields.map((f,i)=><TextInput key={category+f} id={`lw-field-${i}`} labelText={f} value={fields[f]??''} required={f===spec.title_field} maxLength={12000} onChange={e=>setFields(v=>({...v,[f]:e.target.value}))}/>)}</div><TextArea id="lw-edit-reason" labelText="登记或修订依据" required minLength={3} maxLength={1000} value={reason} onChange={e=>setReason(e.target.value)}/></form>{save.error&&<Notice kind="error" title="未能保存" subtitle={save.error.message}/>}</Modal>;
}

function showValue(value:string|undefined){if(!value)return '未提供';return value;}
