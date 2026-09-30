import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Dropdown, InlineLoading, InlineNotification, Modal, TextArea, TextInput } from '@carbon/react';
import { createPlanningRecord, listPlanningRecords, importApplicationRecords } from '../../generated/smartlib-api';

type Kind = 'application' | 'action' | 'review';
interface Field { key: string; name: string; type?: 'date' | 'ids' | 'area'; optional?: boolean };
const fields: Record<Kind, Field[]> = {
  application: [
    {key:'reference',name:'申请编号'}, {key:'title',name:'申请名称'}, {key:'applicant_id',name:'申请人学者对象编号'}, {key:'project_kind_id',name:'项目种类对象编号'},
    {key:'deadline',name:'申请截止日',type:'date'}, {key:'submitted_on',name:'提交日期',type:'date'}, {key:'decided_on',name:'决定日期（非未决时必填）',type:'date',optional:true},
    {key:'project_id',name:'正式项目对象编号（获批后可填写）',optional:true}, {key:'prior_publication_ids',name:'截止日前论文对象编号（逗号分隔）',type:'ids',optional:true}, {key:'evidence',name:'来源文件及定位依据',type:'area'},
  ],
  action: [
    {key:'title',name:'支持措施名称'}, {key:'rationale',name:'为什么采取此措施',type:'area'}, {key:'beneficiary_ids',name:'受支持对象编号（学者、机构或方向，逗号分隔）',type:'ids'},
    {key:'support',name:'提供的资源或支持',type:'area'}, {key:'expected_change',name:'希望改善什么及观察口径',type:'area'}, {key:'started_on',name:'开始日期',type:'date'}, {key:'review_on',name:'计划复盘日期',type:'date'},
    {key:'decision_reason',name:'采纳、调整或拒绝的原因',type:'area'}, {key:'baseline_analysis_id',name:'基线快照编号（可选）',optional:true}, {key:'evidence',name:'决策及支持来源依据',type:'area'},
  ],
  review: [
    {key:'action_id',name:'支持措施记录编号'}, {key:'reviewed_on',name:'实际复盘日期',type:'date'}, {key:'observed_change',name:'实际变化与观察结果',type:'area'},
    {key:'alternative_explanations',name:'自然增长及其他可能解释',type:'area'}, {key:'decision_reason',name:'继续、调整或停止的原因',type:'area'}, {key:'followup_analysis_id',name:'后续结果快照编号（可选）',optional:true}, {key:'evidence',name:'复盘证据及定位',type:'area'},
  ],
};
const decisions: Record<Kind, Record<string,string>> = {
  application: {pending:'未决',awarded:'获批',declined:'未获批',withdrawn:'撤回'},
  action: {proposed:'建议',adopted:'采纳',adjusted:'调整',declined:'拒绝',completed:'完成'},
  review: {continue:'继续',adjust:'调整',stop:'停止',complete:'完成'},
};
const display = (v: unknown): string => v == null ? '未填写' : typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' ? String(v) : JSON.stringify(v);
const kindNames: Record<Kind,string> = {application:'申请记录',action:'支持措施',review:'复盘记录'};
export function PlanningRegister({mode,active}: {mode:'applications'|'actions';active:boolean}) {
  const client = useQueryClient();
  const [csvFile,setCsvFile] = useState<File|null>(null);
  const [supersedes,setSupersedes] = useState<string | null>(null);
  const [kind,setKind] = useState<Kind|null>(null), [values,setValues] = useState<Record<string,string>>({});
  const records = useQuery({queryKey:['research-planning'],enabled:active,queryFn:async({signal}) => {
    const response = await listPlanningRecords({signal});
    if(response.error) throw new Error('记录暂不可用，请检查权限或重试。');
    return response.data;
  }});
  const save = useMutation({mutationFn:async() => {
    if(!kind) throw new Error('请选择记录类型');
    const payload:Record<string,unknown> = {decision:values.decision ?? Object.keys(decisions[kind])[0]};
    for(const f of fields[kind]) {
      const value = (values[f.key] ?? '').trim();
      if(!f.optional && !value) throw new Error(`请填写${f.name}`);
      if(value) payload[f.key] = f.type === 'ids' ? value.split(/[,，\n]/).map(x=>x.trim()).filter(Boolean) : value;
    }
    const response = await createPlanningRecord({body:{kind,supersedes_id:supersedes,[kind]:payload}});
    if(response.error) {
      const detail = response.error.detail;
      throw new Error(typeof detail === 'string' ? detail : '保存失败，请核对必填项、日期、对象编号和访问权限。');
    }
    return response.data;
  },onSuccess:() => {setKind(null);void client.invalidateQueries({queryKey:['research-planning']});}});
  const importCsv = useMutation({mutationFn:async() => {
    if(!csvFile) throw new Error('请选择CSV文件');
    if(csvFile.size>2*1024*1024) throw new Error('CSV不能超过2 MB');
    const response = await importApplicationRecords({body:{file:csvFile}});
    if(response.error) throw new Error(typeof response.error.detail === 'string' ? response.error.detail : '导入失败，整批未写入，请检查文件格式、对象编号及权限。');
    return response.data;
  },onSuccess:()=>{setCsvFile(null);void client.invalidateQueries({queryKey:['research-planning']});}});
  const revised = new Set(records.data?.map(r=>r.supersedes_id).filter(Boolean));
  const shown = records.data?.filter(r => mode === 'applications' ? r.kind === 'application' : r.kind !== 'application') ?? [];
  const latestApplications = shown.filter(r=>r.kind==='application' && !revised.has(r.record_id));
  const open = (k:Kind, defaults:Record<string,string>={}, previous:string|null=null) => {setSupersedes(previous);save.reset();setValues(defaults);setKind(k);};
  return <section className="sg-planning-register">
    <h3>{mode === 'applications' ? '项目申请与成长记录' : '支持措施与效果复盘'}</h3>
    <InlineNotification kind="info" title={mode === 'applications' ? '完整申请分母尚未提供，不计算获批率' : '记录支持前后变化，不自动判定因果效果'} subtitle={mode === 'applications' ? '可登记获批、未获批和未决申请，关联截止日前论文与正式项目。仅年份、没有精确发表日期的论文不能纳入前期基础。' : '先保存分析快照作为基线，再登记支持对象、资源、预期变化和复盘日期；复盘保留其他可能解释及后续决定。'} hideCloseButton />
    <div className="sg-analysis-library"><Button onClick={()=>open(mode === 'applications' ? 'application' : 'action')}>新增{mode === 'applications' ? '申请记录' : '支持措施'}</Button>{mode === 'actions' && <Button kind="tertiary" onClick={()=>open('review')}>登记复盘</Button>}</div>
    {mode === 'applications' && <section className="sg-strategy-evidence"><h4>CSV批量接入</h4><p>UTF-8，最多500条、2 MB；先校验整批，任一行失败都不写入。不包含示例申请数据。</p><a download="申请记录模板.csv" href={`data:text/csv;charset=utf-8,${encodeURIComponent('reference,title,applicant_id,project_kind_id,deadline,submitted_on,decision,decided_on,project_id,prior_publication_ids,evidence\n')}`}>下载空白模板</a><p>日期使用 YYYY-MM-DD；decision 填 pending、awarded、declined 或 withdrawn；多个前期论文编号用分号分隔。</p><input aria-label="申请记录CSV文件" type="file" accept=".csv,text/csv" onChange={e=>{importCsv.reset();setCsvFile(e.target.files?.[0]??null);}} /><Button disabled={!csvFile || importCsv.isPending} onClick={()=>importCsv.mutate()}>校验并导入整批</Button>{importCsv.isError && <InlineNotification kind="error" title={importCsv.error.message} hideCloseButton />}{importCsv.isSuccess && <InlineNotification kind="success" title={`已导入 ${importCsv.data.length} 条申请记录`} hideCloseButton />}</section>}
    {records.isPending && <InlineLoading description="正在读取记录…" />}
    {records.isError && <><InlineNotification kind="error" title={records.error.message} hideCloseButton /><Button kind="ghost" onClick={()=>void records.refetch()}>重试</Button></>}
    {save.isSuccess && <InlineNotification kind="success" title="已保存真实记录及来源" hideCloseButton />}
    {records.isSuccess && !shown.length && <p>尚无{mode === 'applications' ? '申请数据。待科研部门提供完整记录后逐步接入。' : '支持或复盘记录。只有实际采取或正式讨论的措施才应登记。'}</p>}
    <p>当前身份最近1000条记录，非全校完整台账。所有写入保留原始来源，历史记录不覆盖。</p>
    {mode === 'applications' && latestApplications.length > 0 && <section className="sg-strategy-evidence"><h4>已登记申请分布（按最新版本）</h4><p>{Object.entries(decisions.application).map(([key,name])=>`${name} ${latestApplications.filter(r=>r.payload.decision===key).length} 条`).join('；')}。分母未经完整性确认，不计算成功率。</p></section>}
    {shown.map(r => <article key={r.record_id} className="sg-strategy-evidence"><h4>{kindNames[r.kind as Kind]} · {display(r.payload.title ?? r.payload.action_id ?? r.record_id)}</h4><p>记录编号：<code>{r.record_id}</code> · {new Date(r.created_at).toLocaleString('zh-CN')}</p><dl>{Object.entries(r.payload).map(([key,v]) => <div key={key}><dt>{key==='decision'?'当前决定':fields[r.kind as Kind].find(f=>f.key===key)?.name ?? key}</dt><dd>{key==='decision' ? decisions[r.kind as Kind][display(v)] ?? String(v) : Array.isArray(v) ? v.join('、') || '未填写' : display(v)}</dd></div>)}</dl>{r.kind==='application' && <section><h4>申请与成长时间线</h4><p>提交：{display(r.payload.submitted_on)} → 截止：{display(r.payload.deadline)} → 决定：{display(r.payload.decided_on)}</p>{typeof r.payload.project_id==='string' && <Link to={`/outputs/${r.payload.project_id}`}>查看正式项目及关联成果</Link>}{Array.isArray(r.payload.prior_publication_ids) && r.payload.prior_publication_ids.map(id=>typeof id==='string'?<p key={id}><Link to={`/outputs/${id}`}>查看截止日前论文 · {id}</Link></p>:null)}<p>截止日前论文只代表登记的基础材料；尚未进行结果预测或获批归因。</p></section>}{!revised.has(r.record_id) && <Button kind="ghost" onClick={()=>open(r.kind as Kind,Object.fromEntries(Object.entries(r.payload).filter(([,v])=>v!=null).map(([k,v])=>[k,Array.isArray(v)?v.join(','):display(v)])),r.record_id)}>修订记录（保留旧版）</Button>}{revised.has(r.record_id) && <p>历史版本，已有后续修订。</p>}{r.kind==='action' && !revised.has(r.record_id) && <Button kind="ghost" onClick={()=>open('review',{action_id:r.record_id})}>为此措施登记复盘</Button>}</article>)}
    <Modal open={kind!==null} modalHeading={kind ? `新增${kindNames[kind]}` : ''} primaryButtonText={save.isPending?'保存中…':'保存记录'} secondaryButtonText="取消" primaryButtonDisabled={save.isPending} onRequestSubmit={()=>save.mutate()} onRequestClose={()=>{if(!save.isPending)setKind(null);}}>
      <p>本次将新增一条正式管理记录，保留来源；不会修改已有论文、项目或核验状态。</p>
      {kind && <Dropdown id="planning-decision" titleText="决定状态" label="选择状态" items={Object.keys(decisions[kind])} itemToString={v=>v?(decisions[kind][v] ?? v):''} selectedItem={values.decision ?? Object.keys(decisions[kind])[0]} onChange={({selectedItem})=>setValues({...values,decision:selectedItem??''})} />}
      {kind && fields[kind].map(f => f.type==='area' ? <TextArea key={f.key} id={`planning-${f.key}`} labelText={f.name} value={values[f.key]??''} maxLength={4000} onChange={e=>setValues({...values,[f.key]:e.target.value})} /> : <TextInput key={f.key} id={`planning-${f.key}`} labelText={f.name} type={f.type==='date'?'date':'text'} value={values[f.key]??''} onChange={e=>setValues({...values,[f.key]:e.target.value})} />)}
      {save.isError && <InlineNotification kind="error" title={save.error.message} hideCloseButton />}
    </Modal>
  </section>;
}
