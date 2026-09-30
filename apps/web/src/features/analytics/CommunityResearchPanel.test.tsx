import { FundingKindsExpansion } from './FundingKindsExpansion';
import { summarizeCommunityResearch } from './communityResearchSummary';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { CommunityResearchPanel } from './CommunityResearchPanel';
import type { CommunityResearch } from '../../generated/smartlib-api';
const r: CommunityResearch = {
  input_hash:'test', funding:[{key:'f',basis:'funded',name:'国自然',object_id:'kind',category_label:'境内中央公共资助',publication_ids:['p1'],project_ids:['project'],relation_ids:['r1']}],
  directions:[{key:'d',object_id:'direction',scheme:'NSFC_APPLICATION_CODE',version:'2026',name:'肿瘤学',code:'H18',publication_ids:['p1'],primary_publication_ids:['p1'],secondary_publication_ids:[],relation_ids:['r2']}],
  intersections:[{funding_key:'f',direction_key:'d',publication_ids:['p1']}], projects:{project:'项目一'},
  funded_publication_ids:['p1'],representative_publication_ids:[],unlinked_publication_ids:['p2'],unclassified_publication_ids:['p2'],
};
describe('CommunityResearchPanel',()=>{
  it('uses all community papers as denominator and drills down matching papers',()=>{
    render(<MemoryRouter><CommunityResearchPanel research={r} papers={['p1','p2']} titles={new Map([['p1','共同论文甲']])}/></MemoryRouter>);
    expect(screen.getByText('1 篇 / 50.0%')).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('region',{name:'基金项目与学科方向明细，可滚动'})).getByText('查看 1 篇论文', {selector:'summary'}));
    expect(screen.getByRole('link',{name:'共同论文甲'})).toHaveAttribute('href','/outputs/p1');
    fireEvent.click(screen.getByRole('button',{name:'基金项目分布'}));
    fireEvent.click(screen.getByText('1 个关联项目'));
    expect(screen.getByRole('link',{name:'项目一'})).toHaveAttribute('href','/outputs/project');
    fireEvent.change(screen.getByLabelText('基金项目关联方式'),{target:{value:'representative'}});
    expect(screen.getByRole('status')).toHaveTextContent('暂无关联记录');
  });
});


it('summarizes unique projects, tied directions and same-paper intersections within one version',()=>{
  const f = r.funding[0], d = r.directions[0];
  if (!f || !d) throw new Error('Missing fixture');
  const data: CommunityResearch = {...r,
    funding:[...r.funding,{...f,key:'f2',object_id:null}, {...f,key:'rep',basis:'representative',project_ids:['representative-only']}],
    directions:[...r.directions,{...d,key:'d2',object_id:'d2',name:'药理学'}, {...d,key:'old',version:'2025',publication_ids:['p2']}],
  };
  const m=summarizeCommunityResearch(data,['p1','p2','p1'],JSON.stringify(['NSFC_APPLICATION_CODE','2026']));
  expect(m).toMatchObject({total:2,funded:1,projects:1,kinds:1,untyped:1,classified:1,directionCount:2,multiple:1,cross:1,leadingCount:1});
  expect(m.leading).toHaveLength(2);
  const old=summarizeCommunityResearch(data,['p1','p2'],JSON.stringify(['NSFC_APPLICATION_CODE','2025']));
  expect(old).toMatchObject({classified:1,directionCount:1,multiple:0,cross:0});
  const empty=summarizeCommunityResearch(data,[],JSON.stringify(['NSFC_APPLICATION_CODE','2026']));
  expect(empty).toMatchObject({total:0,projects:0,classified:0,cross:0});
});

it('shows all six source category counts without expanding',()=>{
  const m=summarizeCommunityResearch(r,['p1','p2'],'');
  render(<MemoryRouter><FundingKindsExpansion rows={m.categoryCounts} missing={m.missingCategoryCount}/></MemoryRouter>);
  const region=screen.getByRole('group',{name:'六类资助分类的种类数量'});
  expect(region.children).toHaveLength(6);
  expect(within(region).getByText('境内中央公共资助：1 种')).toBeVisible();
  expect(screen.queryByText('展开六类资助分类')).not.toBeInTheDocument();
  expect(within(region).queryByText('国自然')).not.toBeInTheDocument();
});
