import { useDeferredValue, useRef, useState } from 'react';
import { useLocation, useOutletContext, Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Add, Download, Information, Renew } from '@carbon/icons-react';
import { Button, InlineLoading, Modal, Pagination, Search, Select, SelectItem, TextArea, TextInput } from '@carbon/react';
import { Notice } from '../../shared/components/Notice';
import type { KnowledgeHubOutletContext } from './KnowledgeHubShell';
import { cellText, downloadCsv, hubRequest, type HubOptions, type HubRow, type HubTable } from './hubApi';
import { hubCatalog, labels, type HubSection } from './hubCatalog';

export function HubNote({children}:{children:React.ReactNode}){return <p className="kh-work-note"><Information size={17} aria-hidden="true"/><span>{children}</span></p>;}
export function HubHeading({title,description,children}:{title:string;description:string;children?:React.ReactNode}){return <header className="kh-page-header"><div><p>图书馆知识中台</p><h1>{title}</h1><span>{description}</span></div><div className="kh-header-actions">{children}</div></header>;}
const stateOptions:Partial<Record<HubSection,string[]>>={resources:['draft','active','paused','retired'],applications:['draft','active','paused','retired'],rules:['active','paused'],governance:['acknowledged','resolved','wont_fix']};
const template=[['metric_code','metric_name','period','organization','value','unit','source_reference','note']];
interface SchemaField {field_path:string;data_type:string;nullable:boolean;classification:string;description:string}
const emptyField=():SchemaField=>({field_path:'',data_type:'string',nullable:true,classification:'internal',description:''});
export function HubWorkspace(){
  const route=useLocation().pathname.split('/').at(-1);
  const section=(route==='library-metrics'?'library':route) as HubSection;
  if(!(section in hubCatalog))return <section className="kh-page"><h1>未找到工作区</h1><Link to="/knowledge-hub">返回总览</Link></section>;
  return <HubDataPage key={section} section={section}/>;
}
function HubDataPage({section}:{section:HubSection}){
  const config=hubCatalog[section];const {permissions}=useOutletContext<KnowledgeHubOutletContext>();const writable=permissions.includes('knowledge_hub.manage');
  const [q,setQ]=useState('');const query=useDeferredValue(q);const [page,setPage]=useState(1);const [size,setSize]=useState(25);
  const [editor,setEditor]=useState(false);const [revision,setRevision]=useState<HubRow|null>(null);const [values,setValues]=useState<Record<string,string>>({});const [fields,setFields]=useState<SchemaField[]>([emptyField()]);
  const [selected,setSelected]=useState<HubRow|null>(null);const [state,setState]=useState('');const [reason,setReason]=useState('');
  const [message,setMessage]=useState('');const [evidence,setEvidence]=useState<unknown>(null);const form=useRef<HTMLFormElement>(null);const upload=useRef<HTMLInputElement>(null);
  const cache=useQueryClient();
  const list=useQuery({queryKey:['hub',section,query,page,size],queryFn:()=>hubRequest<HubTable>(`/workbench/${section}?q=${encodeURIComponent(query)}&page=${page}&page_size=${size}`)});
  const options=useQuery({queryKey:['hub','options'],queryFn:()=>hubRequest<HubOptions>('/workbench/options'),enabled:editor});
  const allSettings=useQuery({queryKey:['hub','settings','banner'],queryFn:()=>hubRequest<HubTable>('/workbench/settings?page_size=100'),enabled:section==='settings'});
  const refresh=async()=>{await cache.invalidateQueries({queryKey:['hub']});await cache.invalidateQueries({queryKey:['knowledge-hub-overview']});};
  const save=useMutation({mutationFn:()=>{
    const body:Record<string,unknown>={reason:values.reason??''};
    for(const field of config.fields??[]) body[field.key]=values[field.key]??'';
    if(section==='library')body.value=Number(values.value);
    if(section==='licenses')for(const key of ['allowed_content','allowed_purposes','prohibited_purposes'])body[key]=(values[key]??'').split(/[\n,，]/).map(s=>s.trim()).filter(Boolean);
    if(section==='metadata'){body.fields=fields;body.base_version=Number(values.base_version??0);}
    if(section==='settings')body.base_version=Number(values.base_version??0);
    if(revision){body.base_version=revision.version;return hubRequest<unknown>(`/library/${revision.id}/revision`,body);}
    return hubRequest<unknown>(`/workbench/${section}`,body);
  },onSuccess:()=>{setEditor(false);setMessage('已保存，记录与操作审计已写入。');void refresh();}});
  const update=useMutation({mutationFn:()=>hubRequest(`/workbench/${section}/${selected?.id??''}/state`,{state,reason,base_updated_at:selected?.updated_at}),onSuccess:()=>{setSelected(null);setMessage('处理状态已更新。');void refresh();}});
  const run=useMutation({mutationFn:(id:string)=>hubRequest(`/workbench/rules/${id}/run`,{reason:'馆员在规则工作台执行质量检查'}),onSuccess:(data)=>{setEvidence(data);void refresh();}});
  const history=useMutation({mutationFn:(id:string)=>hubRequest(`/quality-runs/${id}`),onSuccess:setEvidence});
  const batch=useMutation({mutationFn:(file:File)=>{const data=new FormData();data.append('file',file);return hubRequest<{count:number}>('/workbench/library/import',data);},onSuccess:data=>{setMessage(`已完整导入 ${data.count} 条月度记录。`);void refresh();}});
  const rows=list.data?.items??[];const error=list.error??batch.error??run.error??history.error;
  const selectField=(key:string,value:string)=>{setValues(previous=>{const next={...previous,[key]:value};if(section==='metadata'&&key==='data_asset_id')next.base_version=String(options.data?.assets.find(a=>a.id===value)?.version??0);if(section==='settings'&&key==='code'){const current=allSettings.data?.items.find(row=>row.code===value);next.value=typeof current?.value==='string'?current.value:'';next.base_version=String(typeof current?.version==='number'?current.version:0);}return next;});};
  const startEditor=()=>{setRevision(null);const initial:Record<string,string>=Object.fromEntries((config.fields??[]).map(f=>[f.key,f.options?.[0]??'']));if(section==='settings'){const current=allSettings.data?.items.find(row=>row.code===initial.code);initial.value=typeof current?.value==='string'?current.value:'';initial.base_version=String(typeof current?.version==='number'?current.version:0);}setValues(initial);setFields([emptyField()]);save.reset();setEditor(true);};
  return <div className="kh-page kh-workspace">
    <HubHeading title={config.title} description={config.description}><Button kind="ghost" renderIcon={Renew} onClick={()=>void refresh()}>刷新</Button>{config.action&&writable&&<Button renderIcon={Add} disabled={section==='settings'&&(allSettings.isPending||allSettings.isError)} onClick={startEditor}>{config.action}</Button>}</HubHeading>
    <HubNote>{config.note}</HubNote>
    {message&&<Notice kind="success" title={message} onCloseButtonClick={()=>setMessage('')}/>}
    {error&&<Notice kind="error" title="数据读取或操作未完成" subtitle={error.message} actions={<Button kind="ghost" onClick={()=>void refresh()}>重试读取</Button>}/>}
    {section==='applications'&&<section className="kh-built-in"><div><strong>学者星图</strong><p>已接通公共对象、知识图谱和科研分析服务；共用本中台的数据导入与治理链路。</p></div><Link className="cds--btn cds--btn--tertiary" to="/">进入应用</Link></section>}
    {section==='access'&&<section className="kh-section"><h2>当前可用权限</h2><div className="kh-permissions">{permissions.map(p=><code key={p}>{p}</code>)}</div></section>}
    {section==='governance'&&<div className="kh-shortcuts"><Link to="/knowledge-hub/changes">清洗与变更 →</Link><Link to="/knowledge-hub/verifications/publications">论文核验 →</Link><Link to="/knowledge-hub/rules">质量规则 →</Link></div>}
    {section==='library'&&<div className="kh-shortcuts"><Link to="/knowledge-hub/library">馆务业务台账 →</Link><Link to="/knowledge-hub/analysis">查看月度指标趋势 →</Link><Button size="sm" kind="ghost" onClick={()=>downloadCsv('馆务月度指标模板.csv',template)}>下载 CSV 模板</Button>{writable&&<><Button size="sm" kind="tertiary" disabled={batch.isPending} onClick={()=>upload.current?.click()}>导入 CSV</Button><input ref={upload} hidden type="file" accept=".csv" onChange={e=>{const file=e.target.files?.[0];if(file)batch.mutate(file);e.target.value='';}}/></>}</div>}
    <section className="kh-data-panel">
      <div className="kh-table-toolbar"><Search id={`hub-${section}-search`} labelText={`检索${config.title}`} placeholder="输入名称、编码或关键词" value={q} onChange={e=>{setQ(e.target.value);setPage(1);}}/><span>{list.data?`共 ${list.data.total} 条`:'正在查询'}</span><Button kind="ghost" size="sm" renderIcon={Download} disabled={!rows.length} onClick={()=>downloadCsv(`${config.title}-第${page}页.csv`,[config.columns.map(c=>c[1]),...rows.map(row=>config.columns.map(([key])=>row[key]))])}>导出当前页</Button></div>
      {list.isFetching&&<InlineLoading description="正在读取工作区数据"/>}
      <div className="kh-table-scroll" role="region" aria-label={`${config.title}列表，可滚动`} tabIndex={0}>
        <table><thead><tr>{config.columns.map(([key,label])=><th key={key}>{label}</th>)}<th>操作</th></tr></thead><tbody>{rows.map(row=><tr key={row.id}>{config.columns.map(([key])=>{const text=cellText(row[key]);return <td key={key}>{['state','severity','last_result'].includes(key)?<span className={`kh-status kh-status-${text}`}>{['sources','licenses'].includes(section)&&key==='state'?(text==='approved'?'已授权':text==='pending'?'待授权核实':labels[text]??text):labels[text]??text}</span>:labels[text]??text}</td>;})}<td><div className="kh-row-actions"><Button kind="ghost" size="sm" onClick={()=>setEvidence(row)}>详情</Button>{writable&&stateOptions[section]&&<Button kind="ghost" size="sm" onClick={()=>{setSelected(row);setState(stateOptions[section]?.[0]??'');setReason('');update.reset();}}>处理</Button>}{section==='library'&&writable&&<Button kind="ghost" size="sm" onClick={()=>{setRevision(row);setValues({...Object.fromEntries(Object.entries(row).map(([k,v])=>[k,v==null||v===''?'':cellText(v)])),metric_name:cellText(row.name),reason:''});save.reset();setEditor(true);}}>修订</Button>}{section==='rules'&&<><Button kind="ghost" size="sm" onClick={()=>history.mutate(row.id)}>运行记录</Button>{writable&&row.engine==='publication_completeness_v1'&&<Button kind="ghost" size="sm" disabled={run.isPending||row.state!=='active'} onClick={()=>run.mutate(row.id)}>执行检查</Button>}</>}</div></td></tr>)}</tbody></table>
        {!list.isPending&&!list.isError&&!rows.length&&<div className="kh-empty"><strong>{q?'没有匹配记录':'尚无可见记录'}</strong><p>{q?'可缩短关键词或清空检索条件。':config.action?`可通过“${config.action}”建立真实记录。`:'接入真实数据或完成相应业务流程后，记录将出现在这里。'}</p></div>}
      </div>
      <Pagination page={page} pageSize={size} pageSizes={[25,50,100]} totalItems={list.data?.total??0} backwardText="上一页" forwardText="下一页" itemsPerPageText="每页" pageNumberText="页码" itemRangeText={(min,max,total)=>`第 ${min}–${max} 条，共 ${total} 条`} pageRangeText={(_,total)=>`共 ${total} 页`} onChange={({page:next,pageSize})=>{setPage(next);setSize(pageSize);}}/>
    </section>
    {editor&&<Modal open modalHeading={revision?'修订馆务记录':config.action??'登记'} primaryButtonText={save.isPending?'正在保存':'保存'} secondaryButtonText="取消" primaryButtonDisabled={save.isPending||options.isPending||options.isError} onRequestClose={()=>!save.isPending&&setEditor(false)} onRequestSubmit={()=>{if(form.current?.reportValidity())save.mutate();}}>
      <form ref={form} className="kh-editor" onSubmit={e=>{e.preventDefault();save.mutate();}}>
        {(config.fields??[]).map(field=>{const common={id:`hub-edit-${field.key}`,labelText:field.label,value:values[field.key]??'',required:!field.optional&&section!=='settings',disabled:Boolean(revision&&!['value','source_reference','note'].includes(field.key))};return field.options||field.lookup?<Select key={field.key} {...common} onChange={e=>selectField(field.key,e.target.value)}>{field.lookup&&<SelectItem value="" text="请选择"/>}{field.options?.map(v=><SelectItem key={v} value={v} text={labels[v]??v}/>)}{field.lookup&&options.data?.[field.lookup].map(o=><SelectItem key={o.id} value={o.id} text={o.name}/>)}</Select>:field.type==='textarea'?<TextArea key={field.key} {...common} onChange={e=>selectField(field.key,e.target.value)}/>:<TextInput key={field.key} {...common} type={field.type==='date'?'date':field.type==='number'?'number':'text'} min={field.type==='number'?0:undefined} step="any" onChange={e=>selectField(field.key,e.target.value)}/>;})}
        {section==='metadata'&&<div className="kh-schema-editor"><h3>字段定义</h3>{fields.map((field,index)=><div className="kh-schema-row" key={index}><TextInput id={`field-${index}`} labelText="字段路径" required value={field.field_path} onChange={e=>setFields(fs=>fs.map((f,i)=>i===index?{...f,field_path:e.target.value}:f))}/><Select id={`type-${index}`} labelText="类型" value={field.data_type} onChange={e=>setFields(fs=>fs.map((f,i)=>i===index?{...f,data_type:e.target.value}:f))}>{['string','integer','decimal','boolean','date','datetime','object','array'].map(t=><SelectItem key={t} value={t} text={t}/>)}</Select><Select id={`privacy-${index}`} labelText="敏感等级" value={field.classification} onChange={e=>setFields(fs=>fs.map((f,i)=>i===index?{...f,classification:e.target.value}:f))}>{['public','internal','sensitive','restricted'].map(t=><SelectItem key={t} value={t} text={t}/>)}</Select><label><input type="checkbox" checked={!field.nullable} onChange={e=>setFields(fs=>fs.map((f,i)=>i===index?{...f,nullable:!e.target.checked}:f))}/> 必填</label><Button kind="ghost" size="sm" disabled={fields.length===1} onClick={()=>setFields(fs=>fs.filter((_,i)=>i!==index))}>移除</Button></div>)}<Button kind="tertiary" size="sm" onClick={()=>setFields(fs=>[...fs,emptyField()])}>添加字段</Button></div>}
        <TextArea id="hub-reason" labelText="登记或变更依据" required minLength={3} value={values.reason??''} onChange={e=>setValues(v=>({...v,reason:e.target.value}))}/>
      </form>{(save.error??options.error)&&<Notice kind="error" title="无法保存" subtitle={(save.error??options.error)?.message??'请重试'}/>}
    </Modal>}
    {selected&&<Modal open modalHeading="更新处理状态" primaryButtonText="确认保存" secondaryButtonText="取消" primaryButtonDisabled={update.isPending||reason.trim().length<3} onRequestClose={()=>!update.isPending&&setSelected(null)} onRequestSubmit={()=>update.mutate()}><HubNote>此操作会更新台账并记录审计。若其他馆员已经修改记录，本次提交会被拒绝。</HubNote><Select id="hub-record-state" labelText="状态" value={state} onChange={e=>setState(e.target.value)}>{stateOptions[section]?.map(s=><SelectItem key={s} value={s} text={labels[s]??s}/>)}</Select><TextArea id="hub-state-reason" labelText="处理依据（必填）" value={reason} onChange={e=>setReason(e.target.value)}/>{update.error&&<Notice kind="error" title="未能更新" subtitle={update.error.message}/>}</Modal>}
    {evidence!==null&&<Modal open passiveModal modalHeading="记录与依据" onRequestClose={()=>setEvidence(null)}><Evidence value={evidence}/></Modal>}
  </div>;
}
const detailLabels:Record<string,string>={...Object.fromEntries(Object.values(hubCatalog).flatMap(c=>c.columns)),id:'记录编号',total:'检查论文数',missing:'缺失论文数',examples:'缺失论文证据',examples_truncated:'证据列表已截取前100条',note:'说明',scope:'范围',field:'检查字段',title:'论文标题',publication_id:'论文编号',run_state:'检查结果',observed_value:'观测值',expected_value:'期望值',started_at:'检查时间',details:'检查依据',description:'说明',resolution:'处理结论'};
function Evidence({value}:{value:unknown}){
 if(Array.isArray(value))return value.length?<div className="kh-evidence">{(value as unknown[]).map((v,i)=><section key={i}><Evidence value={v}/></section>)}</div>:<p>暂无记录。</p>;
 if(value!==null&&typeof value==='object')return <dl className="kh-evidence-fields">{Object.entries(value as Record<string, unknown>).map(([key,v])=><div key={key}><dt>{detailLabels[key]??key}</dt><dd>{key==='publication_id'&&typeof v==='string'?<Link to={`/outputs/${v}`}>查看论文 →</Link>:typeof v==='object'&&v!==null?<Evidence value={v}/>:labels[cellText(v)]??cellText(v)}</dd></div>)}</dl>;
 return <span>{cellText(value)}</span>;
}
