import React, {useEffect, useMemo, useRef, useState} from 'react';
import './insights.css';

const TABS = ['Review', 'Health', 'Documentation'];
const SEVERITIES = ['all', 'critical', 'high', 'medium', 'low'];

export default function ProjectInsights({project, request, status, onOpenSource, activeTab, onTabChange}) {
  const [tab, setTab] = useState(activeTab || 'Review');
  const [report, setReport] = useState(null);
  const [docs, setDocs] = useState([]);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [severity, setSeverity] = useState('all');
  const [category, setCategory] = useState('all');
  const [fileFilter, setFileFilter] = useState('');
  const [healthLanguage, setHealthLanguage] = useState('all');
  const [hotspotFilter, setHotspotFilter] = useState('');
  const [explanations, setExplanations] = useState({});
  const selectedDocRef = useRef(null);
  const pollRef = useRef(null);

  useEffect(() => { if (activeTab) setTab(activeTab); }, [activeTab]);

  const refreshSnapshot = async () => {
    try {
      const [analysis, generated] = await Promise.all([
        request(`/api/projects/${project.id}/analysis`),
        request(`/api/projects/${project.id}/docs/generated`),
      ]);
      setReport(analysis);
      setDocs(generated.documents || []);
      if (generated.documents?.length) {
        const current = generated.documents.find(item => item.id === selectedDocRef.current?.id) || generated.documents[0];
        if (current.id !== selectedDocRef.current?.id) {
          const detail = await request(`/api/projects/${project.id}/docs/generated/${current.id}`);
          selectedDocRef.current = detail;
          setSelectedDoc(detail);
        }
      } else {
        selectedDocRef.current = null;
        setSelectedDoc(null);
      }
      return {analysis, generated};
    } catch (reason) { setError(reason.message); }
  };

  const stopPolling = () => { if (pollRef.current) window.clearInterval(pollRef.current); pollRef.current = null; };
  const startPolling = () => {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      const snapshot = await refreshSnapshot();
      if (!snapshot) return;
      const analysisPending = ['QUEUED', 'RUNNING'].includes(snapshot.analysis.status);
      const docsPending = ['QUEUED', 'RUNNING'].includes(snapshot.generated.status);
      if (!analysisPending && !docsPending) stopPolling();
    }, 2000);
  };
  const load = async () => { setError(''); await refreshSnapshot(); };

  useEffect(() => {
    let mounted = true;
    refreshSnapshot().then(snapshot => {
      if (mounted && snapshot && (['QUEUED', 'RUNNING'].includes(snapshot.analysis.status) || ['QUEUED', 'RUNNING'].includes(snapshot.generated.status))) startPolling();
    });
    return () => { mounted = false; stopPolling(); };
  }, [project.id]);

  const findings = report?.findings || [];
  const categories = useMemo(() => [...new Set(findings.map(item => item.category))].sort(), [findings]);
  const filtered = findings.filter(item =>
    (severity === 'all' || item.severity === severity) &&
    (category === 'all' || item.category === category) &&
    item.path.toLowerCase().includes(fileFilter.toLowerCase()),
  );
  const health = report?.health;
  const entity = health?.entity_counts || {};
  const maxLanguageCount = Math.max(1, ...Object.values(health?.language_distribution || {}));
  const visibleLanguages = Object.entries(health?.language_distribution || {}).filter(([language]) => healthLanguage === 'all' || language === healthLanguage);
  const visibleHotspots = (health?.dependency_hotspots || []).filter(item => `${item.symbol} ${item.path || ''}`.toLowerCase().includes(hotspotFilter.toLowerCase()));

  const runScan = async () => {
    setBusy(true); setError('');
    try { setReport(await request(`/api/projects/${project.id}/analysis/scan`, {method: 'POST'})); startPolling(); }
    catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };

  const generateDocs = async () => {
    setBusy(true); setError('');
    try { await request(`/api/projects/${project.id}/docs/generate`, {method: 'POST'}); await load(); startPolling(); }
    catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };

  const selectDoc = async item => {
    setError('');
    try { const detail = await request(`/api/projects/${project.id}/docs/generated/${item.id}`); selectedDocRef.current = detail; setSelectedDoc(detail); }
    catch (reason) { setError(reason.message); }
  };

  const exportDoc = () => {
    if (!selectedDoc) return;
    const blob = new Blob([selectedDoc.markdown], {type: 'text/markdown;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${selectedDoc.kind}-${selectedDoc.scope_key?.split('/').pop() || 'project'}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const explain = async finding => {
    setExplanations(current => ({...current, [finding.id]: {...current[finding.id], loading: true}}));
    try {
      const result = await request(`/api/projects/${project.id}/analysis/explain/${finding.id}`, {method: 'POST'});
      setExplanations(current => ({...current, [finding.id]: {result}}));
    } catch (reason) { setExplanations(current => ({...current, [finding.id]: {error: reason.message}})); }
  };

  return <section className="insights-panel" aria-label="Code review, project health, and generated documentation">
    <header className="insights-header"><div><span className="eyebrow">PROJECT INSIGHTS</span><h2>Review, health & docs</h2><small>Successful index revision {report?.index_revision ?? 0}{project.repository_commit_sha ? ` · commit ${project.repository_commit_sha.slice(0, 12)}` : ''} · indexing {status?.replaceAll('_', ' ') || 'unknown'}</small></div><div className="insights-actions"><button onClick={load}>Refresh</button><button className="primary-button" onClick={runScan} disabled={busy || !report?.index_revision}>{busy ? 'Working…' : report?.status === 'QUEUED' || report?.status === 'RUNNING' ? 'Analysis queued…' : 'Run static scan'}</button></div></header>
    <nav className="insights-tabs" aria-label="Project insight views">{TABS.map(item => <button key={item} className={tab === item ? 'active' : ''} onClick={() => { setTab(item); onTabChange?.(item); }}>{item}</button>)}</nav>
    {error && <div className="insights-error" role="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}
    {tab === 'Review' && <div className="insights-content"><div className="insights-subhead"><div><h3>Static code review</h3><p>Rule matches are deterministic signals; they are not proof of exploitable vulnerabilities. AI explanations are optional and labeled separately.</p></div><span className={'analysis-state ' + (report?.status || '').toLowerCase()}>{report?.status || 'Loading'}</span></div>
      {report?.error && <div className="insights-error">{report.error}</div>}
      {report?.status === 'NOT_INDEXED' && <div className="insights-empty">Index this project before reviewing source.</div>}
      {report?.status === 'NOT_RUN' && <div className="insights-empty">No scan exists for this index revision. Run a static scan to create findings and health metrics.</div>}
      {report?.status === 'COMPLETED' && <><div className="finding-filters"><select aria-label="Filter by severity" value={severity} onChange={event => setSeverity(event.target.value)}>{SEVERITIES.map(value => <option key={value} value={value}>{value === 'all' ? 'All severities' : value}</option>)}</select><select aria-label="Filter by category" value={category} onChange={event => setCategory(event.target.value)}><option value="all">All categories</option>{categories.map(value => <option key={value}>{value}</option>)}</select><input aria-label="Filter by file" value={fileFilter} onChange={event => setFileFilter(event.target.value)} placeholder="Filter file path"/><span>{filtered.length} / {findings.length} findings</span></div>
        {filtered.length ? <div className="finding-list">{filtered.map(finding => <article className="finding-card" key={finding.id}><div className="finding-title"><span className={'severity-pill ' + finding.severity}>{finding.severity}</span><span className="finding-category">{finding.category} · {finding.rule_id}</span><b>{finding.title}</b><span className="origin-pill">Rule-confirmed pattern</span></div><p>{finding.description}</p><pre>{finding.evidence}</pre><div className="finding-footer"><span>{finding.path}:{finding.start_line}{finding.end_line !== finding.start_line ? `–${finding.end_line}` : ''}</span><button onClick={() => onOpenSource({file: finding.path, start_line: finding.start_line, end_line: Math.min(finding.end_line, finding.start_line + 99)})}>Open source</button><button onClick={() => explain(finding)} disabled={explanations[finding.id]?.loading}>{explanations[finding.id]?.loading ? 'Asking Gemini…' : 'AI explanation'}</button></div>{explanations[finding.id]?.error && <div className="insights-error">{explanations[finding.id].error}</div>}{explanations[finding.id]?.result && <div className="ai-explanation"><b>AI explanation · {explanations[finding.id].result.answer_mode}</b><p>{explanations[finding.id].result.answer}</p><small>Any additional hypothesis is speculative; the static rule match above is the only confirmed result.</small>{(explanations[finding.id].result.citations || []).map((citation, index) => <button key={index} onClick={() => onOpenSource({file: citation.file, start_line: citation.start_line, end_line: citation.end_line})}>{citation.file}:{citation.start_line}–{citation.end_line}</button>)}</div>}</article>)}</div> : <div className="insights-empty">No findings match these filters. This means no configured rule matched, not that the code is risk-free.</div>}</>}
    </div>}
    {tab === 'Health' && <div className="insights-content"><div className="insights-subhead"><div><h3>Codebase health</h3><p>Metrics are calculated from the current indexed snapshot. Unavailable inputs are shown as unavailable.</p></div><span>Revision {health ? report.index_revision : '—'}</span></div>{!health ? <div className="insights-empty">{report?.status === 'NOT_RUN' ? 'Run the static scan to calculate health metrics.' : `Analysis ${report?.status?.toLowerCase() || 'is loading'}.`}</div> : <><div className="health-cards">{[["Files", health.total_files], ["Source lines", health.source_lines], ["Functions", entity.function ?? 0], ["Classes / interfaces", (entity.class ?? 0) + (entity.interface ?? 0)], ["Modules", entity.module ?? 0], ["Review findings", findings.length], ["Avg Python complexity", health.complexity.available ? health.complexity.average_python_cyclomatic : 'Unavailable'], ["Test coverage", health.test_coverage.available ? `${health.test_coverage.value}%` : 'Unavailable']].map(([label, value]) => <article key={label}><small>{label}</small><b>{value}</b></article>)}</div><p className="metric-definition">Source lines count nonblank, non-comment lines. Complexity is approximate Python AST decision count + 1. {health.complexity.definition} Test coverage is unavailable because no reliable coverage artifact is attached to this index revision.</p><div className="health-grid"><section><h4>Language distribution · files</h4><select aria-label="Filter health by language" value={healthLanguage} onChange={event => setHealthLanguage(event.target.value)}><option value="all">All languages</option>{Object.keys(health.language_distribution).sort().map(language => <option key={language}>{language}</option>)}</select>{visibleLanguages.map(([language, count]) => <div className="language-bar" key={language}><span>{language}</span><i><b style={{width: `${count / maxLanguageCount * 100}%`}}/></i><strong>{count}</strong></div>)}</section><section><h4>Dependency hotspots</h4><input aria-label="Filter dependency hotspots" placeholder="Filter symbol or file" value={hotspotFilter} onChange={event => setHotspotFilter(event.target.value)}/>{visibleHotspots.length ? visibleHotspots.map((item, index) => <button className="hotspot-row" key={`${item.symbol}-${index}`} disabled={!item.path} onClick={() => onOpenSource({file: item.path, start_line: item.start_line || 1, end_line: (item.start_line || 1) + 20})}><span>{item.symbol}</span><small>{item.references} references{item.path ? ` · ${item.path}` : ''}</small></button>) : <div className="insights-empty">No dependency hotspots match this filter.</div>}</section></div></>}</div>}
    {tab === 'Documentation' && <div className="insights-content"><div className="insights-subhead"><div><h3>Documentation drafts</h3><p>Generated from indexed source and graph facts. Unknown commands, endpoints, and descriptions are left explicit.</p><span className="analysis-state">{report?.documentation_status || 'NOT_STARTED'}</span></div><button className="primary-button" onClick={generateDocs} disabled={busy || !report?.index_revision}>{docs.length ? 'Regenerate docs' : 'Generate docs'}</button></div><div className="docs-workspace"><nav className="docs-list" aria-label="Generated documents">{docs.map(item => <button key={item.id} className={selectedDoc?.id === item.id ? 'selected' : ''} onClick={() => selectDoc(item)}>{item.title}<small>{item.kind} · rev {report?.index_revision}</small></button>)}{!docs.length && <div className="insights-empty">No documentation exists for this revision yet.</div>}</nav><div className="docs-preview">{selectedDoc ? <><header><div><b>{selectedDoc.title}</b><small>Revision {selectedDoc.index_revision} · {selectedDoc.source_refs?.length || 0} source files</small></div><button onClick={exportDoc}>Export Markdown</button></header><pre>{selectedDoc.markdown}</pre></> : <div className="insights-empty">Generate documentation to preview the overview, setup draft, modules, detected API routes, and Mermaid architecture diagram.</div>}</div></div></div>}
  </section>;
}
