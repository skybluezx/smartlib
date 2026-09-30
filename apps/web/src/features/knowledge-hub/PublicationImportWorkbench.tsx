import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Checkmark, DocumentAdd, Download, Information, Upload } from '@carbon/icons-react';
import {
  Button,
  FileUploaderDropContainer,
  InlineNotification,
  NumberInput,
  Tabs,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  TextArea,
  TextInput,
} from '@carbon/react';
import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  submitBatchPublicationImport,
  submitSinglePublicationImport,
  type PublicationImportResult,
} from '../../shared/api/smartlib';
import type { KnowledgeHubOutletContext } from './KnowledgeHubShell';

const template = [
  ['论文题名', '期刊名称', '发表年份', 'DOI', 'PMID', 'PMCID', '作者列表', '获批人', '代表性论著编号'],
  ['示例论文题名', '示例期刊', '2026', '10.1000/example', '', '', 'Zhang San;Li Si', '张三', '1'],
].map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(',')).join('\n');

function downloadTemplate() {
  const url = URL.createObjectURL(new Blob([`\ufeff${template}`], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = '论文批量导入模板.csv';
  anchor.click();
  URL.revokeObjectURL(url);
}

function ImportResult({ result }: { result: PublicationImportResult }) {
  return <section className="kh-import-result" aria-live="polite">
    <header><Checkmark size={24} /><div><strong>论文记录已接收</strong><span>批次 {result.dataset_version}</span></div></header>
    <div><span><small>接收</small><strong>{result.accepted_count}</strong></span><span><small>具备自动核验资格</small><strong>{result.automatic_eligible_count}</strong></span><span><small>直接待人工核验</small><strong>{result.manual_review_count}</strong></span></div>
    {result.manual_review_count > 0 && <details><summary>查看不能自动核验的原因</summary><ul>{result.items.filter((item) => !item.automatic_verification_eligible).map((item) => <li key={item.record_id}><strong>{item.title}</strong><span>{item.eligibility_reasons.join('；')}</span></li>)}</ul></details>}
  </section>;
}

function StandardPanel() {
  return <section className="kh-import-standard">
    <div><span>01</span><h2>最低接收标准</h2><p>必须提供论文题名。系统允许 DOI、年份暂缺的历史记录入库，但会直接进入人工核验。</p></div>
    <div><span>02</span><h2>自动核验资格</h2><p>题名、DOI、发表年份齐全；声明成果归属人时，还要提供作者列表。满足资格只是进入自动队列，不等于核验通过。</p></div>
    <div><span>03</span><h2>自动通过标准</h2><p>DOI 精确命中，题名、年份、期刊及可用标识符一致，所有适用的阻断项通过，且没有后续全文或元数据冲突。</p></div>
  </section>;
}

export function PublicationImportWorkbench() {
  const { permissions } = useOutletContext<KnowledgeHubOutletContext>();
  const canImport = permissions.includes('publication_intake.submit');
  const queryClient = useQueryClient();
  const [sourceLabel, setSourceLabel] = useState('人工录入');
  const [title, setTitle] = useState('');
  const [journal, setJournal] = useState('');
  const [year, setYear] = useState<number | ''>('');
  const [doi, setDoi] = useState('');
  const [pmid, setPmid] = useState('');
  const [pmcid, setPmcid] = useState('');
  const [authors, setAuthors] = useState('');
  const [awardee, setAwardee] = useState('');
  const [workNumber, setWorkNumber] = useState('');
  const [batchLabel, setBatchLabel] = useState('批量文件上传');
  const [batchFile, setBatchFile] = useState<File | null>(null);
  const [result, setResult] = useState<PublicationImportResult | null>(null);

  const finish = async (value: PublicationImportResult) => {
    setResult(value);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['publication-verifications'] }),
      queryClient.invalidateQueries({ queryKey: ['knowledge-hub-overview'] }),
    ]);
  };
  const single = useMutation({
    mutationFn: () => submitSinglePublicationImport(sourceLabel, {
      title: title.trim(), journal_name: journal.trim() || undefined,
      publication_year: year === '' ? undefined : year, doi: doi.trim() || undefined,
      pmid: pmid.trim() || undefined, pmcid: pmcid.trim() || undefined,
      authors: authors.split(/[;；\n]+/).map((value) => value.trim()).filter(Boolean),
      awardee_name: awardee.trim() || undefined,
      representative_work_number: workNumber.trim() || undefined,
    }),
    onSuccess: finish,
  });
  const batch = useMutation({
    mutationFn: () => {
      if (!batchFile) throw new Error('请先选择 CSV 或 XLSX 文件');
      return submitBatchPublicationImport(batchLabel, batchFile);
    },
    onSuccess: finish,
  });

  return <div className="kh-page kh-import-page">
    <header className="kh-page-header"><div><p>数据导入 / 论文</p><h1>论文导入</h1><span>先按统一字段契约接收记录，再根据证据完整度分流到自动核验或人工核验</span></div></header>
    <StandardPanel />
    <div className="kh-import-rule-note"><Information size={20} /><p><strong>“进入自动核验队列”不等于“自动核验通过”。</strong>只有外部权威证据和所有阻断项均通过，状态才会变成“自动确认”；后续新证据产生冲突时会自动改成“待重新核验”或“核验冲突”。</p></div>
    {!canImport && <InlineNotification lowContrast hideCloseButton kind="warning" title="当前角色只有查看权限" subtitle="论文导入需要知识中台管理员权限。" />}
    <section className="kh-import-workspace">
      <Tabs>
        <TabList aria-label="论文导入方式"><Tab>单篇录入</Tab><Tab>批量导入</Tab></TabList>
        <TabPanels>
          <TabPanel><form className="kh-single-import" onSubmit={(event) => { event.preventDefault(); single.mutate(); }}>
            <div className="kh-import-form-grid">
              <TextInput id="publication-title" labelText="论文题名 *" value={title} onChange={(event) => setTitle(event.target.value)} />
              <TextInput id="publication-journal" labelText="期刊名称" value={journal} onChange={(event) => setJournal(event.target.value)} />
              <NumberInput id="publication-year" label="发表年份" min={1500} max={2200} value={year} onChange={(_event, state) => setYear(state.value === '' ? '' : Number(state.value))} />
              <TextInput id="publication-doi" labelText="DOI" helperText="提供 DOI 才具备自动核验资格" value={doi} onChange={(event) => setDoi(event.target.value)} />
              <TextInput id="publication-pmid" labelText="PMID" value={pmid} onChange={(event) => setPmid(event.target.value)} />
              <TextInput id="publication-pmcid" labelText="PMCID" value={pmcid} onChange={(event) => setPmcid(event.target.value)} />
              <TextInput id="publication-awardee" labelText="成果归属人" helperText="填写后必须同时提供作者列表" value={awardee} onChange={(event) => setAwardee(event.target.value)} />
              <TextInput id="publication-work-number" labelText="代表性论著编号" value={workNumber} onChange={(event) => setWorkNumber(event.target.value)} />
            </div>
            <TextArea id="publication-authors" labelText="作者列表" helperText="作者之间用分号或换行分隔，并尽量保持论文原始顺序" rows={4} value={authors} onChange={(event) => setAuthors(event.target.value)} />
            <TextInput id="publication-source" labelText="数据来源名称 *" value={sourceLabel} onChange={(event) => setSourceLabel(event.target.value)} />
            {single.isError && <InlineNotification lowContrast kind="error" title="单篇导入失败" subtitle={single.error.message} />}
            <Button type="submit" renderIcon={DocumentAdd} disabled={!canImport || !title.trim() || !sourceLabel.trim() || single.isPending}>{single.isPending ? '正在提交…' : '提交并进入核验流程'}</Button>
          </form></TabPanel>
          <TabPanel><div className="kh-batch-import">
            <header><div><h2>上传标准数据文件</h2><p>支持不超过 20 MB 的 UTF-8 CSV 或 XLSX；最多 5,000 条。系统先校验整份文件，有错误时不会部分导入。</p></div><Button kind="tertiary" renderIcon={Download} onClick={downloadTemplate}>下载 CSV 模板</Button></header>
            <div className="kh-batch-columns"><strong>标准列名</strong><span>论文题名 *</span><span>期刊名称</span><span>发表年份</span><span>DOI</span><span>PMID</span><span>PMCID</span><span>作者列表</span><span>获批人</span><span>代表性论著编号</span></div>
            <TextInput id="publication-batch-source" labelText="数据来源名称 *" value={batchLabel} onChange={(event) => setBatchLabel(event.target.value)} />
            <FileUploaderDropContainer accept={['.csv', '.xlsx']} labelText="拖放文件到这里，或点击选择文件" multiple={false} disabled={!canImport} onAddFiles={(_event, { addedFiles }) => setBatchFile(addedFiles[0] ?? null)} />
            {batchFile && <div className="kh-selected-import-file"><Upload size={20} /><span><strong>{batchFile.name}</strong><small>{(batchFile.size / 1024 / 1024).toFixed(2)} MB</small></span></div>}
            {batch.isError && <InlineNotification lowContrast kind="error" title="批量导入失败" subtitle={batch.error.message} />}
            <Button renderIcon={Upload} disabled={!canImport || !batchFile || !batchLabel.trim() || batch.isPending} onClick={() => batch.mutate()}>{batch.isPending ? '正在校验并导入…' : '校验整批并提交'}</Button>
          </div></TabPanel>
        </TabPanels>
      </Tabs>
    </section>
    {result && <ImportResult result={result} />}
  </div>;
}
