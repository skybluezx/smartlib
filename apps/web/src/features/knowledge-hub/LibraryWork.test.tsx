import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LibraryWork } from './LibraryWork';
import { hubRequest } from './hubApi';
import type * as Api from './hubApi';
vi.mock('./hubApi',async original=>({...await original<typeof Api>(),hubRequest:vi.fn()}));
const request=vi.mocked(hubRequest);
const category={code:'reader_training',name:'读者培训',group:'读者服务',fields:['时间','内容','听众人数'],title_field:'内容',date_field:'时间',audience_field:'听众人数'};
const row={id:'r1',category:'reader_training',title:'模拟检索培训',mode:'demo',state:'active',version:2,fields:{时间:'2025-03',内容:'模拟检索培训',听众人数:'30'},warnings:[],origin:{file:'读者培训.csv',row:2}};
const overview={summary:{records:1,categories:1,unknown_dates:0,needs_attention:0},categories:[{...category,category:'reader_training',records:1,audience_covered:1,audience_total:30}],years:[{year:2025,records:1}],options:{years:[2025],departments:[]}};
function setup(entry='',permissions=['knowledge_hub.read','knowledge_hub.manage']){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});const router=createMemoryRouter([{path:'/knowledge-hub',element:<Outlet context={{permissions}}/>,children:[{path:'library',element:<LibraryWork/>}]}],{initialEntries:['/knowledge-hub/library'+entry]});render(<QueryClientProvider client={client}><RouterProvider router={router}/></QueryClientProvider>);return router;}
beforeEach(()=>{request.mockReset();request.mockImplementation(path=>Promise.resolve(path.endsWith('/catalog')?[category]:path.includes('/overview')?overview:path.includes('/records?')?{items:[row],total:1}:[]));});
describe('library work ledger',()=>{
 it('keeps formal and demo scope separate and persists workspace tab',async()=>{const router=setup();await screen.findByText('业务分布');expect(request.mock.calls.some(([p])=>p.includes('overview?mode=real'))).toBe(true);fireEvent.change(screen.getByLabelText('数据用途'),{target:{value:'demo'}});fireEvent.click(screen.getByRole('button',{name:'业务台账'}));expect(await screen.findByText('模拟检索培训')).toBeInTheDocument();expect(router.state.location.search).toContain('mode=demo');expect(router.state.location.search).toContain('view=records');expect(request.mock.calls.some(([p])=>p.includes('records?mode=demo'))).toBe(true);});
 it('preserves category and provenance while saving a versioned revision',async()=>{setup('?view=records&mode=demo');fireEvent.click(await screen.findByRole('button',{name:'修订'}));expect(screen.getByLabelText('业务类型',{selector:'#lw-edit-category'})).toBeDisabled();fireEvent.change(screen.getByLabelText('内容'),{target:{value:'模拟检索培训修订'}});fireEvent.change(screen.getByLabelText('登记或修订依据'),{target:{value:'校对原始记录'}});fireEvent.click(screen.getByRole('button',{name:'保存事项'}));await waitFor(()=>expect(request.mock.calls.find(([path])=>path==='/library-work/records/r1/revision')?.[1]).toMatchObject({mode:'demo',base_version:2,reason:'校对原始记录',fields:{内容:'模拟检索培训修订'}}));});
 it('does not offer mutation to read-only users',async()=>{setup('?view=records',['knowledge_hub.read']);await screen.findByText('模拟检索培训');expect(screen.queryByRole('button',{name:'修订'})).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'登记事项'})).not.toBeInTheDocument();});
 it('requires an error-free preview and acknowledgement before import',async()=>{setup('?mode=demo');fireEvent.click(await screen.findByRole('button',{name:'导入工作表'}));expect(screen.getByRole('button',{name:'确认导入'})).toBeDisabled();expect(screen.getByRole('button',{name:'上传并预检'})).toBeDisabled();expect(screen.getByLabelText('本次导入用途')).toHaveValue('demo');});
});
