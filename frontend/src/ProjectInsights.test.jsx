// @vitest-environment jsdom
import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import ProjectInsights from './ProjectInsights.jsx';

afterEach(cleanup);

const finding = {id: 'f-1', rule_id: 'SEC-DYNAMIC-EVAL', severity: 'high', category: 'security', title: 'Dynamic code execution call', description: 'A call site matched a static rule.', remediation: 'Avoid evaluating strings.', path: 'src/handler.py', start_line: 12, end_line: 12, evidence: 'return eval(value)', origin: 'static_rule'};

function mockRequest(path) {
  if (path.endsWith('/analysis')) return Promise.resolve({project_id: 'p1', index_revision: 3, status: 'COMPLETED', documentation_status: 'COMPLETED', health: {total_files: 2, source_lines: 30, language_distribution: {python: 2}, entity_counts: {function: 1, class: 1}, dependency_hotspots: [], complexity: {available: true, average_python_cyclomatic: 1, definition: 'Python AST decisions + 1.'}, test_coverage: {available: false, value: null}}, findings: [finding]});
  if (path.endsWith('/docs/generated')) return Promise.resolve({status: 'COMPLETED', documents: [{id: 'd1', kind: 'overview', title: 'Project overview', scope_key: '', source_refs: ['src/handler.py']}]});
  if (path.endsWith('/docs/generated/d1')) return Promise.resolve({id: 'd1', kind: 'overview', title: 'Project overview', scope_key: '', index_revision: 3, markdown: '# Project overview\n\nSource: src/handler.py#L1', source_refs: ['src/handler.py']});
  if (path.includes('/analysis/explain/')) return Promise.resolve({answer: 'This is a dynamic execution call. Hypothesis: input may be untrusted; this is unconfirmed.', answer_mode: 'fallback', citations: [{file: finding.path, start_line: 12, end_line: 12}]});
  return Promise.resolve({});
}

describe('ProjectInsights', () => {
  it('shows loading, empty, and retryable API error states', async () => {
    let rejectSnapshot;
    let analysisCalls = 0;
    const request = vi.fn(path => {
      if (path.endsWith('/analysis')) {
        analysisCalls += 1;
        return analysisCalls === 1
          ? new Promise((_resolve, reject) => { rejectSnapshot = reject; })
          : Promise.resolve({project_id: 'p1', index_revision: 0, status: 'NOT_INDEXED', findings: []});
      }
      return Promise.resolve({status: 'NOT_STARTED', documents: []});
    });
    render(<ProjectInsights project={{id: 'p1'}} request={request} status="NOT_STARTED"/>);
    expect(await screen.findByText('Loading')).toBeTruthy();
    rejectSnapshot(new Error('Analysis endpoint unavailable'));
    expect((await screen.findByRole('alert')).textContent).toContain('Analysis endpoint unavailable');
    fireEvent.click(screen.getByRole('button', {name: 'Refresh'}));
    expect(await screen.findByText(/Index this project before reviewing source/)).toBeTruthy();
  });

  it('shows versioned metrics, filters rule findings, labels AI hypotheses, and previews generated Markdown', async () => {
    const request = vi.fn((path, options) => path.includes('/analysis/explain/') ? mockRequest(path) : options?.method === 'POST' ? Promise.resolve({status: 'QUEUED'}) : mockRequest(path));
    render(<ProjectInsights project={{id: 'p1', repository_commit_sha: 'abcdef123456789'}} request={request} status="COMPLETED" onOpenSource={vi.fn()}/>);
    expect(await screen.findByText('Dynamic code execution call')).toBeTruthy();
    expect(screen.getByText(/Rule-confirmed pattern/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: 'AI explanation'}));
    expect(await screen.findByText(/This is a dynamic execution call/)).toBeTruthy();
    expect(screen.getByText(/speculative; the static rule match above is the only confirmed result/)).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', {name: 'Filter by severity'}), {target: {value: 'low'}});
    expect(screen.getByText(/No findings match these filters/)).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', {name: 'Filter by severity'}), {target: {value: 'high'}});
    expect(screen.getByText('Dynamic code execution call')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', {name: 'Health'}));
    expect(await screen.findByText('30')).toBeTruthy();
    expect(screen.getByText('Unavailable')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', {name: 'Documentation'}));
    expect(await screen.findByText((_, element) => element?.tagName === 'PRE' && element.textContent.includes('# Project overview'))).toBeTruthy();
    expect(screen.getByRole('button', {name: 'Export Markdown'})).toBeTruthy();
  });
});
