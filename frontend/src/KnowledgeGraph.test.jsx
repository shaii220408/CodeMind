// @vitest-environment jsdom
import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import KnowledgeGraph from './KnowledgeGraph.jsx';

afterEach(cleanup);

describe('KnowledgeGraph', () => {
  it('shows loading, empty, and recoverable request-error states', async () => {
    let resolveGraph;
    const request = vi.fn()
      .mockImplementationOnce(() => new Promise(resolve => { resolveGraph = resolve; }))
      .mockRejectedValueOnce(new Error('Graph service unavailable'))
      .mockResolvedValueOnce({nodes: [], edges: [], supported_languages: []});
    render(<KnowledgeGraph projectId="project-empty" refreshToken={0} request={request}/>);
    expect(await screen.findByText('Loading graph…')).toBeTruthy();
    resolveGraph({nodes: [], edges: [], supported_languages: []});
    expect(await screen.findByText(/No graph entities are indexed yet/)).toBeTruthy();
    expect(screen.getByText(/No indexed languages/)).toBeTruthy();
    expect(screen.getByRole('button', {name: 'Zoom in'})).toBeTruthy();
    expect(screen.getByRole('button', {name: 'Fit graph'})).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: 'Refresh graph'}));
    expect((await screen.findByRole('alert')).textContent).toContain('Graph service unavailable');
    fireEvent.click(screen.getByRole('button', {name: 'Refresh graph'}));
    expect(await screen.findByText(/No graph entities are indexed yet/)).toBeTruthy();
    expect(screen.getByText(/No indexed languages/)).toBeTruthy();
    expect(screen.getByRole('button', {name: 'Zoom in'})).toBeTruthy();
    expect(screen.getByRole('button', {name: 'Fit graph'})).toBeTruthy();
  });

  it('filters nodes, requests direct impact, and opens the selected source range', async () => {
    const request = vi.fn(async path => {
      if (path.includes('/graph/impact?')) {
        return {direct_dependents: [], transitive_dependents: [], note: 'Static relationships only.'};
      }
      return {
        nodes: [
          {id: 'function-1', kind: 'function', name: 'load_user', qualified_name: 'auth.load_user', path: 'src/auth.py', start_line: 8, end_line: 14},
          {id: 'function-2', kind: 'function', name: 'save_user', qualified_name: 'auth.save_user', path: 'src/auth.py', start_line: 16, end_line: 20},
        ],
        edges: [],
        supported_languages: ['python'],
      };
    });
    const onOpenSource = vi.fn();
    render(<KnowledgeGraph projectId="project-1" refreshToken={0} request={request} onOpenSource={onOpenSource}/>);

    const node = await screen.findByRole('button', {name: 'function auth.load_user'});
    fireEvent.click(node);
    await waitFor(() => expect(request).toHaveBeenCalledWith(expect.stringContaining('/graph/impact?node_id=function-1')));
    fireEvent.click(screen.getByRole('button', {name: 'Open source'}));
    expect(onOpenSource).toHaveBeenCalledWith({file: 'src/auth.py', start_line: 8, end_line: 14});

    fireEvent.change(screen.getByRole('textbox', {name: 'Search graph nodes'}), {target: {value: 'save_user'}});
    expect(screen.queryByRole('button', {name: 'function auth.load_user'})).toBeNull();
    expect(screen.getByRole('button', {name: 'function auth.save_user'})).toBeTruthy();
  });
});
