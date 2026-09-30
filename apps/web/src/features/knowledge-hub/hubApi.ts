import { runtimeConfig } from '../../shared/config/runtime';
export type HubRow = Record<string,unknown> & {id:string};
export interface HubTable {items:HubRow[];total:number;page:number;page_size:number}
export type HubOptions = Record<'sources'|'domains'|'assets', {id:string;name:string;version?:number}[]>;
export async function hubRequest<T>(path:string,body?:unknown):Promise<T> {
  const multipart=body instanceof FormData;
  const response=await fetch(`${runtimeConfig.apiBaseUrl.replace(/\/$/,'')}/api/v1/knowledge-hub${path}`,{
    method:body===undefined?'GET':'POST',credentials:'same-origin',
    ...(!multipart?{headers:{'Content-Type':'application/json'}}:{}),
    ...(body===undefined?{}:{body:multipart?body:JSON.stringify(body)}),
  });
  const data:unknown=await response.json();
  if(!response.ok){
    const detail=typeof data==='object'&&data!==null&&'detail' in data?data.detail:undefined;
    throw new Error(typeof detail==='string'?detail:`操作未完成（${response.status}），请检查必填项和字段格式。`);
  }
  return data as T;
}
export function cellText(value:unknown):string {
  if(value==null||value==='')return '未提供';
  if(typeof value==='boolean')return value?'是':'否';
  if(Array.isArray(value))return value.map(cellText).join('、')||'未提供';
  if(typeof value==='object')return JSON.stringify(value);
  return typeof value==='string'||typeof value==='number'||typeof value==='bigint'?String(value):'未提供';
}
export function downloadCsv(name:string, rows:unknown[][]){
  const escape=(v:unknown)=>{const text=cellText(v);return `"${(/^[=+@\-\t\r]/.test(text)?"'":"")+text.replace(/"/g,'""')}"`;};
  const link=document.createElement('a');const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(row=>row.map(escape).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
  link.href=url;link.download=name;link.click();URL.revokeObjectURL(url);
}
