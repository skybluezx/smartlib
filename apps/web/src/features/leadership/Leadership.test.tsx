import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi, afterEach } from 'vitest';
import { emptyScope, latestMatters, readScope, scopeParams, type RecordRow, type Summary } from './api';
import { LeadershipTalent } from './LeadershipPages';
import { MatterBoard } from './MatterBoard';
import { LeadershipShell } from './LeadershipShell';
import { leaderPages } from './catalog';
const summary:Summary={scope:emptyScope,scope_name:'可访问样本',papers:[{object_id:'paper1',title:'样本论文',year:2024,journal_name:'测试期刊',version:1}],scholars:[{object_id:'person1',name:'学者甲',papers:['paper1'],organizations:['署名机构']}],organizations:[],years:[],coverage:{publications:1,scholars:1,organizations:0,with_authors:1,with_affiliations:0,missing_year:0},sources:[],generated_at:'2026-09-30',method_version:'test',boundary:'样本范围',analysis_policy:'test'};
function renderPage(child:React.ReactNode){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});return render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<Outlet context={{scope:emptyScope,summary,search:'',session:{can_write:true,role_verified:false}}}/> }><Route index element={child}/></Route></Routes></MemoryRouter></QueryClientProvider>);}
afterEach(()=>vi.unstubAllGlobals());
describe('leadership role workspace',()=>{
 it('preserves scope across links and rejects malformed IDs',()=>{
 const scope={...emptyScope,start_year:2024,end_year:2026,organization_id:'00000000-0000-4000-8000-000000000001'};
 expect(readScope(scopeParams(scope))).toEqual(scope);
 expect(readScope(new URLSearchParams('start_year=garbage&organization_id=bad'))).toEqual(emptyScope);
 expect(leaderPages).toHaveLength(10);
 });
 it('shows latest matter versions without confusing closed status with recruitment outcome',()=>{
 const rows=[{record_id:'old',kind:'matter',supersedes_id:null},{record_id:'new',kind:'matter',supersedes_id:'old'}] as RecordRow[];
 expect(latestMatters(rows).map(r=>r.record_id)).toEqual(['new']);
 });
 it('drills scoped scholar counts into paper evidence',()=>{
 renderPage(<LeadershipTalent/>);
 fireEvent.click(screen.getByRole('button',{name:'1 篇'}));
 expect(screen.getByRole('link',{name:'样本论文'})).toHaveAttribute('href','/outputs/paper1');
 expect(screen.getByText('不等于学校教职工总数')).toBeInTheDocument();
 });
 it('does not save a cancelled or incomplete matter',async()=>{
 const fetch=vi.fn<(input:RequestInfo|URL,options?:RequestInit)=>Promise<Response>>().mockResolvedValue(new Response('[]',{status:200}));vi.stubGlobal('fetch',fetch);
 renderPage(<MatterBoard category="cultivation" title="支持跟踪"/>);
 await screen.findByText('尚无符合条件的事项。请只登记真实议题与已取得的依据，不创建演示业务记录。');
 fireEvent.click(screen.getByRole('button',{name:'登记事项'}));
 expect(screen.getByRole('button',{name:'保存事项'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'取消'}));
 expect(fetch.mock.calls.every(([,options])=>options?.method==='GET')).toBe(true);
 });
 it('denies unauthorized session instead of rendering leader data',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:403,json:()=>Promise.resolve({detail:'当前身份未获学校领导工作台权限'})}));
 renderPage(<LeadershipShell/>);
 expect(await screen.findByText('当前身份未获学校领导工作台权限')).toBeInTheDocument();
 expect(screen.queryByRole('navigation',{name:'学校领导导航'})).not.toBeInTheDocument();
 });
 it('highlights only the current page and refreshes shared workspace queries',async()=>{
 vi.stubGlobal('fetch',vi.fn((input:RequestInfo|URL)=>{const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;return Promise.resolve({ok:true,json:()=>Promise.resolve(url.endsWith('/session')?{can_write:true,role_verified:false}:url.endsWith('/summary')?summary:url.includes('scope-options')?{organizations:[]}:[])});}));
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
 const invalidate=vi.spyOn(client,'invalidateQueries');
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/leadership/talent']}><Routes><Route path="/leadership" element={<LeadershipShell/>}><Route path="talent" element={<LeadershipTalent/>}/></Route></Routes></MemoryRouter></QueryClientProvider>);
 await screen.findByRole('heading',{name:'人才事实清单'});
 expect(screen.getByRole('link',{name:'人才全景'})).toHaveClass('cds--side-nav__link--current');
 expect(screen.getByRole('link',{name:'决策总览'})).not.toHaveClass('cds--side-nav__link--current');
 expect(screen.getByRole('link',{name:'决策总览'})).not.toHaveAttribute('aria-current','page');
 fireEvent.click(screen.getByRole('button',{name:'刷新数据'}));
 expect(typeof invalidate.mock.calls[0]?.[0]?.predicate).toBe('function');
 });
});
