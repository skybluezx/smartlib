import { useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Button, Checkbox, InlineLoading, Modal, Select, SelectItem, TextArea } from '@carbon/react';
import { hubRequest } from './hubApi';
import { HubNote } from './HubWorkspace';
import { Notice } from '../../shared/components/Notice';
import { type WorkBatch, type WorkCategory, modeName } from './libraryWorkTypes';

export function LibraryImport({mode,batchId,categories,writable,onClose,onSaved}:{mode:'real'|'demo';batchId:string|null;categories:WorkCategory[];writable:boolean;onClose:()=>void;onSaved:(n:number,reused:boolean,mode:'real'|'demo')=>void}){
 const [category,setCategory]=useState('');const [selected,setSelected]=useState<File|null>(null);const [preview,setPreview]=useState<WorkBatch|null>(null);const [confirmed,setConfirmed]=useState(false);const [reason,setReason]=useState('');const [usage,setUsage]=useState(mode);const input=useRef<HTMLInputElement>(null);
 const previous=useQuery({queryKey:['library-work','batch',batchId],queryFn:()=>hubRequest<WorkBatch>('/library-work/batches/'+(batchId??'')),enabled:!!batchId});
 const batch=preview??previous.data;
 const check=useMutation({mutationFn:()=>{if(!selected)throw new Error('请选择文件');const data=new FormData();data.append('file',selected);data.append('mode',usage);data.append('category',category);return hubRequest<WorkBatch>('/library-work/preview',data);},onSuccess:data=>{setPreview(data);setConfirmed(false);}});
 const commit=useMutation({mutationFn:()=>{if(!batch)throw new Error('请先预检');return hubRequest<{count:number;reused:boolean}>(`/library-work/batches/${batch.id}/commit`,{confirm:confirmed,reason});},onSuccess:r=>onSaved(r.count,r.reused,batch?.mode??usage)});
 const error=check.error??commit.error??previous.error;
 return <Modal open size="lg" modalHeading={batch?'检查导入结果':'导入馆务工作表'} primaryButtonText={commit.isPending?'正在导入':batch?.state==='imported'?'已导入':batch?.already_imported?'确认（不会重复写入）':'确认导入'} secondaryButtonText="关闭" primaryButtonDisabled={!writable||!batch||batch.state==='imported'||batch.errors.length>0||!confirmed||reason.trim().length<3||commit.isPending} onRequestClose={()=>!commit.isPending&&!check.isPending&&onClose()} onRequestSubmit={()=>commit.mutate()}>
 <HubNote>支持单个 XLSX、UTF-8 CSV 或包含工作表的 ZIP，最大 20 MB / 10000 条事项。XLSX 优先读取“总表”，跳过“报告”；不会执行公式。正式与模拟用途入库后不能互换。</HubNote>
 {!batch&&<div className="lw-import-form"><Select id="lw-import-mode" labelText="本次导入用途" value={usage} onChange={e=>setUsage(e.target.value as 'real'|'demo')}><SelectItem value="real" text="正式数据"/><SelectItem value="demo" text="模拟数据 · 不计入正式统计"/></Select><Select id="lw-import-category" labelText="业务类型" value={category} onChange={e=>setCategory(e.target.value)}><SelectItem value="" text="按文件名自动识别（多类型 ZIP 请选择此项）"/>{categories.map(c=><SelectItem key={c.code} value={c.code} text={c.name}/>)}</Select><label htmlFor="lw-import-file">选择工作表</label><input id="lw-import-file" ref={input} type="file" accept=".xlsx,.csv,.zip" onChange={e=>{setSelected(e.target.files?.[0]??null);check.reset();}}/><Button kind="tertiary" disabled={!selected||check.isPending||!writable} onClick={()=>check.mutate()}>上传并预检</Button></div>}
 {(check.isPending||previous.isPending&&!!batchId)&&<InlineLoading description="正在读取文件并检查原始字段"/>}
 {error&&<Notice kind="error" title="导入尚未完成" subtitle={error.message}/>}
 {batch&&<><div className="lw-import-summary"><strong>{batch.filename}</strong><span>{modeName(batch.mode)} · {batch.count} 条可识别事项 · {batch.warning_count} 条有补充提示 · {batch.errors.length} 处错误</span><p>跳过 {batch.skipped_rows} 行空白、说明或重复表头。完整确认后才写入业务台账。</p></div><div className="lw-field-tags">{Object.entries(batch.categories).map(([name,n])=><span key={name}>{name} {n} 项</span>)}</div>
 {batch.already_imported&&<HubNote>此文件已经导入；再次确认不会产生重复事项。</HubNote>}
 {batch.errors.length>0&&<section><h3>需修正后重新上传</h3><ul className="lw-import-errors">{batch.errors.map((e,i)=><li key={i}>{e.file}{e.row!==null?` · 第 ${e.row} 行`:''}：{e.message}</li>)}</ul></section>}
 <h3>记录预览{batch.examples_truncated?'（前 30 条）':''}</h3><div className="lw-preview-table kh-table-scroll"><table><thead><tr><th>事项</th><th>来源</th><th>检查提示</th></tr></thead><tbody>{batch.examples.map((r,i)=><tr key={i}><td>{r.title}</td><td>{r.origin.file} · 第 {r.origin.row} 行</td><td>{r.warnings.join('；')||'未发现字段缺失提示'}</td></tr>)}</tbody></table></div>
 {batch.state!=='imported'&&writable&&<div className="lw-import-confirm"><Checkbox id="lw-import-confirm" labelText={`我已核对来源与预检结果，确认以“${modeName(batch.mode)}”导入。`} checked={confirmed} onChange={(_,v)=>setConfirmed(v.checked)}/><TextArea id="lw-import-reason" labelText="导入依据（至少 3 字）" maxLength={1000} value={reason} onChange={e=>setReason(e.target.value)}/></div>}
 {!batchId&&<Button kind="ghost" onClick={()=>{setPreview(null);commit.reset();check.reset();setSelected(null);}}>重新选择文件</Button>}
 </>}
 </Modal>;
}
