import { runtimeConfig } from '../../shared/config/runtime';
import type { GraphAnalysisQuery } from '../../shared/api/smartlib';
import type { JournalAnalysis } from '../../generated/smartlib-api';
export interface LeaderScope {start_year:number|null;end_year:number|null;organization_id:string|null;custom_scope_id:string|null}
export const emptyScope:LeaderScope={start_year:null,end_year:null,organization_id:null,custom_scope_id:null};
export interface Paper {object_id:string;title:string;year:number|null;journal_name:string|null;version:number}
export interface Person {object_id:string;name:string;papers:string[];organizations:string[]}
export interface Org {object_id:string;name:string;papers:string[];scholar_count:number}
export interface Summary {scope:LeaderScope;scope_name:string;papers:Paper[];scholars:Person[];organizations:Org[];years:{year:number|null;count:number;publication_ids:string[]}[];coverage:{publications:number;scholars:number;organizations:number;with_authors:number;with_affiliations:number;missing_year:number};sources:string[];generated_at:string;method_version:string;boundary:string;analysis_policy:string}
export interface Session {actor_id:string;role_verified:boolean;mode:'authorized'|'development_preview';can_write:boolean}
export type Category='overview'|'research'|'disciplines'|'resources'|'recruitment'|'cultivation'|'teams'|'transfer';
export interface Matter {category:Category;title:string;question:string;evidence:string;responsible_unit:string;next_step:string;review_on:string;status:'proposed'|'investigating'|'tracking'|'closed';object_ids:string[];supersedes_id:string|null;scope:LeaderScope}
export interface RecordRow {record_id:string;kind:'matter'|'report';category:Category;title:string;created_at:string;supersedes_id:string|null;result_hash:string|null;payload:Matter & {scope:LeaderScope;publication_count?:number;summary?:Summary;journals?:JournalAnalysis}}
export interface Resource {object_id:string;name:string;asset_type:string;lifecycle_state:string;description:string|null;updated_at:string;license_count:number;effective_licenses:number}
export async function leaderRequest<T>(path:string,body?:unknown,signal?:AbortSignal):Promise<T>{
 const response=await fetch(`${runtimeConfig.apiBaseUrl.replace(/\/$/,'')}/api/v1/leadership${path}`,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),...(signal?{signal}:{})});
 const data:unknown=await response.json();
 if(!response.ok){const detail=typeof data==='object'&&data!==null&&'detail' in data?data.detail:undefined;throw new Error(typeof detail==='string'?detail:`请求未完成（${response.status}），请检查填写内容或重试。`);}return data as T;
}
export function readScope(params:URLSearchParams):LeaderScope{
 const year=(key:string)=>{const text=params.get(key);const n=Number(text);return text&&Number.isInteger(n)&&n>=1500&&n<=2200?n:null;};
 const id=(key:string)=>{const text=params.get(key);return text&&/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(text)?text:null;};
 return {start_year:year('start_year'),end_year:year('end_year'),organization_id:id('organization_id'),custom_scope_id:id('custom_scope_id')};
}
export function scopeParams(scope:LeaderScope){const p=new URLSearchParams();Object.entries(scope).forEach(([k,v])=>{if(v!==null)p.set(k,String(v));});return p;}
export function graphQuery(scope:LeaderScope):GraphAnalysisQuery{return {...(scope.start_year?{startYear:scope.start_year}:{}),...(scope.end_year?{endYear:scope.end_year}:{}),...(scope.organization_id?{organizationIds:[scope.organization_id]}:{}),...(scope.custom_scope_id?{customScopeId:scope.custom_scope_id}:{})};}
export function latestMatters(rows:RecordRow[]){const old=new Set(rows.map(r=>r.supersedes_id).filter(Boolean));return rows.filter(r=>r.kind==='matter'&&!old.has(r.record_id));}
export function downloadJson(name:string,data:unknown){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
