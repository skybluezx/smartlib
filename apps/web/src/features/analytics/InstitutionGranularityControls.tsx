import { useState } from 'react';
import { Button, ComboBox, Dropdown, FilterableMultiSelect, TextInput } from '@carbon/react';
import { Information } from '@carbon/icons-react';
import { Link } from 'react-router-dom';
import './institutionGranularity.css';

export interface InstitutionSettings { mode: 'root' | 'internal' | 'expanded'; root_ids: string[]; groups: { name: string; member_ids: string[] }[] }
export interface InstitutionOption { id: string; name: string; root_id: string; level: number }
export interface InstitutionContext { groups?: Record<string, {name: string; member_ids: string[]; member_names: Record<string,string>}>; root_only_publication_ids?: string[]; invalid_hierarchy_publication_ids?: string[]; outside_only_publication_ids?: string[]; mapped_publication_count?: number }
const modes = [{ id: 'root', name: '一级机构间合作' }, { id: 'internal', name: '校内单位合作' }, { id: 'expanded', name: '选定一级机构展开' }] as const;
export const defaultInstitutionSettings: InstitutionSettings = {mode:'root',root_ids:[],groups:[]};

export function InstitutionGranularityControls({ options, applied, onApply, context }: {options: InstitutionOption[]; applied: InstitutionSettings; onApply: (settings:InstitutionSettings)=>void; context: InstitutionContext}) {
  const [draft,setDraft] = useState(applied);
  const [name,setName] = useState('');
  const [members,setMembers] = useState<InstitutionOption[]>([]);
  const [revision,setRevision] = useState(0);
  const roots = options.filter(o=>o.level===1);
  const used = new Set(draft.groups.flatMap(g=>g.member_ids));
  const children = options.filter(o=>!used.has(o.id) && (draft.mode==='root' ? o.level===1 : draft.mode==='internal'
    ? o.level===2 && draft.root_ids.includes(o.root_id)
    : (o.level===2 && draft.root_ids.includes(o.root_id)) || (o.level===1 && !draft.root_ids.includes(o.id))));
  const memberLabel = draft.mode==='root' ? '组合成员（一级机构）' : draft.mode==='internal' ? '组合成员（二级机构）' : '组合成员（展开后二级及未展开一级机构）';
  const memberName = (o:InstitutionOption|null) => !o ? '' : draft.mode==='expanded' && o.level===2
    ? `${roots.find(r=>r.id===o.root_id)?.name??''} / ${o.name}` : o.name;
  const valid = draft.mode === 'root' || (draft.mode==='internal' ? draft.root_ids.length===1 : draft.root_ids.length>0);
  const addValid = name.trim().length>0 && members.length>0 && !draft.groups.some(g=>g.name===name.trim());
  const hasUnaddedGroup = name.trim().length > 0 || members.length > 0;
  const changed = JSON.stringify(draft) !== JSON.stringify(applied);
  const resetMembers = () => {setName('');setMembers([]); setRevision(v=>v+1);};
  return <section className="sg-institution-granularity" aria-label="机构分析粒度">
    <h3>分析粒度</h3>
    <h4 className="sg-institution-step">1. 选择分析模式与范围</h4>
    <div className="sg-institution-granularity-fields sg-institution-mode-fields">
      <Dropdown id="institution-granularity" titleText="分析模式" label="选择分析模式" items={[...modes]} itemToString={o=>o?.name??''} selectedItem={modes.find(m=>m.id===draft.mode)} onChange={({selectedItem})=>{if(selectedItem){setDraft({mode:selectedItem.id,root_ids:[],groups:[]});resetMembers();}}}/>
      {draft.mode==='internal' && <ComboBox id="institution-internal-root" titleText="校内分析范围" placeholder="输入机构名称检索" items={roots} shouldFilterItem={({item,inputValue})=>item.name.toLocaleLowerCase().includes((inputValue??'').trim().toLocaleLowerCase())} itemToString={o=>o?.name??''} selectedItem={roots.find(r=>r.id===draft.root_ids[0])??null} onChange={({selectedItem})=>{setDraft({...draft,root_ids:selectedItem?[selectedItem.id]:[],groups:[]});resetMembers();}}/>}
      {draft.mode==='expanded' && <FilterableMultiSelect key={`roots-${draft.mode}`} id="institution-expanded-roots" titleText="展开为二级单位的一级机构" placeholder="搜索并选择多个一级机构" items={roots} itemToString={o=>o?.name??''} initialSelectedItems={roots.filter(r=>draft.root_ids.includes(r.id))} onChange={({selectedItems})=>{setDraft({...draft,root_ids:selectedItems.map(o=>o.id),groups:[]});resetMembers();}}/>}
    </div>
    <p className="sg-institution-note"><Information size={16}/>{draft.mode==='root'?'将下级署名归并到一级机构，同篇去重后计算机构间合作。':draft.mode==='expanded'?'选中机构展开为直属二级单位，深层单位归入其二级机构；其余机构归并到一级。展开后不保留其一级机构节点。':'仅分析所选机构的二级单位；深层单位归并到对应二级单位。可将二级单位编组，未编组单位仍独立参与分析。'} 切换粒度会重新分簇和计算指标，层级关系不计为合作。</p>
    {valid && <div className="sg-institution-groups">
      <h4 className="sg-institution-step">2. {draft.mode==='internal' ? '校内单位自定义组合' : '自定义机构组合'}<span>可选</span></h4>
      <p className="sg-institution-group-help">无需编组可直接应用配置；需要编组时，填写名称并选择成员，点击“添加组合”加入本次配置。</p>
      <div className="sg-institution-granularity-fields">
        <TextInput id="institution-group-name" labelText="组合名称" value={name} maxLength={80} onChange={e=>setName(e.target.value)} placeholder="例如：临床研究组合"/>
        <FilterableMultiSelect key={`members-${revision}`} id="institution-group-members" titleText={memberLabel} placeholder="可搜索、多选" items={children} itemToString={memberName} onChange={({selectedItems})=>setMembers(selectedItems)}/>
        <Button kind="tertiary" disabled={!addValid} onClick={()=>{setDraft({...draft,groups:[...draft.groups,{name:name.trim(),member_ids:members.map(m=>m.id)}]});setName('');resetMembers();}}>添加组合</Button>
      </div>
      {draft.groups.map((g,i)=><div className="sg-institution-group-row" key={g.name}><strong>{g.name}</strong><span>{g.member_ids.map(id=>options.find(o=>o.id===id)?.name??id).join('、')}</span><Button kind="ghost" size="sm" onClick={()=>setDraft({...draft,groups:draft.groups.filter((_,j)=>j!==i)})}>移除组合</Button></div>)}
      <p className="sg-institution-note"><Information size={16}/>同一单位仅能属于一个组合，未编组机构独立保留；组合内共同署名不产生自连接。更换模式或展开机构会清空组合草稿。添加组合只更新配置，完成后在下方统一应用。</p>
    </div>}
    <div className="sg-institution-config-actions">
      <div className="sg-institution-config-status" role="status"><strong>{!valid ? '请先选择分析范围' : hasUnaddedGroup ? '有尚未添加的组合' : changed ? '配置已修改，尚未应用' : '当前配置已应用'}</strong><span>{hasUnaddedGroup ? '请先添加组合，或清空组合输入后继续。' : `本次配置：${modes.find(m=>m.id===draft.mode)?.name} · ${draft.groups.length ? `${draft.groups.length} 个组合` : '不使用自定义组合'}`}</span></div>
      <div className="sg-institution-config-buttons">{hasUnaddedGroup && <Button kind="ghost" onClick={resetMembers}>清空组合输入</Button>}<Button disabled={!valid || hasUnaddedGroup} onClick={()=>onApply(draft)}>应用配置并重新分析</Button></div>
    </div>
    <div className="sg-institution-applied"><strong>当前结果：{modes.find(m=>m.id===applied.mode)?.name}</strong><span>可归入当前粒度的论文 {context.mapped_publication_count??'—'} 篇</span>{applied.groups.length>0 && <span>{applied.groups.length} 个自定义组合</span>}</div>
    {!!context.root_only_publication_ids?.length && <details><summary>仅一级署名、无法分配到下级的论文：{context.root_only_publication_ids.length} 篇（可能同时包含其他可定位署名）</summary><p>这些署名以“下属单位未明确”节点保留参与分析；不虚构二级归属。同篇已有明确下级署名时，不重复保留一级署名。</p>{context.root_only_publication_ids.map(id=><Link key={id} to={`/outputs/${id}`}>查看论文 {id}</Link>)}</details>}
    {!!context.invalid_hierarchy_publication_ids?.length && <details><summary>存在层级缺失、多父级或循环的论文：{context.invalid_hierarchy_publication_ids.length} 篇</summary>{context.invalid_hierarchy_publication_ids.map(id=><Link key={id} to={`/outputs/${id}`}>查看论文 {id}</Link>)}</details>}
    {!!context.outside_only_publication_ids?.length && <p className="sg-institution-note">{context.outside_only_publication_ids.length} 篇仅涉及所选校内范围之外的机构，不生成校内节点。</p>}
  </section>;
}

export function InstitutionName({ id, name, context }: {id:string;name:string;context?:InstitutionContext}) {
  const group=context?.groups?.[id];
  if(id.startsWith('unassigned:')) return <Link to={`/institutions/${id.slice('unassigned:'.length)}`}>{name}</Link>;
  return id.startsWith('group:') ? <details><summary>{name}（组合）</summary>{group?.member_ids.map(member=><p key={member}><Link to={`/institutions/${member}`}>{group.member_names[member]??member}</Link></p>)}</details> : <Link to={`/institutions/${id}`}>{name}</Link>;
}
