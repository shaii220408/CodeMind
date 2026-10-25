// @vitest-environment jsdom
import React from 'react';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {AssistantWorkspace,ExplorerWorkspace,HistoryWorkspace,ImpactWorkspace,OverviewWorkspace} from './WorkspaceViews.jsx';

afterEach(cleanup);

describe('CodeMind workspace pages',()=>{
  it('shows actual overview metrics and routes shortcuts to feature pages',()=>{
    const setPage=vi.fn();
    render(<OverviewWorkspace project={{name:'Payments',repository_url:null}} overview={{file_count:18,chunk_count:52,languages:{python:12,typescript:6}}} files={[]} status="COMPLETED" busy={false} history={[]} branch="" setBranch={vi.fn()} syncRepository={vi.fn()} file={null} setFile={vi.fn()} upload={vi.fn()} setPage={setPage}/>);
    expect(screen.getByText('18')).toBeTruthy();
    expect(screen.getByText('52')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:/Knowledge Graph/}));
    expect(setPage).toHaveBeenCalledWith('graph');
  });

  it('describes replacement upload after a local snapshot is indexed',()=>{
    render(<OverviewWorkspace project={{name:'Payments',repository_url:null}} overview={{file_count:1,chunk_count:2,languages:{java:1}}} files={[{path:'src/Main.java'}]} status="COMPLETED" busy={false} history={[]} branch="" setBranch={vi.fn()} syncRepository={vi.fn()} file={null} setFile={vi.fn()} upload={vi.fn()} setPage={vi.fn()}/>);
    expect(screen.getByText('Upload another ZIP to replace the current indexed snapshot.')).toBeTruthy();
  });
  it('opens an indexed explorer path at its source range',()=>{
    const openSource=vi.fn();
    render(<ExplorerWorkspace files={[{id:'1',path:'src/auth/service.py',language:'python'}]} filter="" setFilter={vi.fn()} openSource={openSource} sourceLoading={false} status="COMPLETED"/>);
    fireEvent.click(screen.getByRole('button',{name:/service.py/}));
    expect(openSource).toHaveBeenCalledWith({file:'src/auth/service.py',start_line:1,end_line:80});
  });

  it('shows the response mode and citation action in the assistant',()=>{
    const openSource=vi.fn();
    render(<AssistantWorkspace project={{name:'Payments',repository_url:null}} status="COMPLETED" busy={false} question="Where is retry?" setQuestion={vi.fn()} history={[{question:'Where is retry?',answer:'The retry loop runs in the worker.',answer_mode:'llm',citations:[] }]} answer={{answer:'The retry loop runs in the worker.',answer_mode:'llm',citations:[{file:'src/worker.py',start_line:20,end_line:24,symbol:'retry'}]}} setAnswer={vi.fn()} ask={vi.fn()} assistantTarget="" setAssistantTarget={vi.fn()} runQuickAction={vi.fn()} loading={false} sourceLoading={false} openSource={openSource}/>);
    expect(screen.getByText(/Gemini · source grounded/)).toBeTruthy();
    expect(screen.getAllByText('The retry loop runs in the worker.')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button',{name:'Open source'}));
    expect(openSource).toHaveBeenCalledWith({file:'src/worker.py',start_line:20,end_line:24,symbol:'retry'});
  });

  it('offers a stop-waiting action while the assistant request is in progress',()=>{
    const cancelAsk=vi.fn();
    render(<AssistantWorkspace project={{name:'Payments',repository_url:null}} status="COMPLETED" busy={false} question="Where is retry?" setQuestion={vi.fn()} history={[]} answer={null} setAnswer={vi.fn()} ask={vi.fn()} cancelAsk={cancelAsk} retryBlocked={false} assistantTarget="" setAssistantTarget={vi.fn()} runQuickAction={vi.fn()} loading={true} sourceLoading={false} openSource={vi.fn()}/>);
    fireEvent.click(screen.getByRole('button',{name:'Stop waiting'}));
    expect(cancelAsk).toHaveBeenCalledTimes(1);
  });

  it('reopens a saved history item in the assistant',()=>{
    const setAnswer=vi.fn(),setQuestion=vi.fn(),setPage=vi.fn();
    render(<HistoryWorkspace history={[{question:'Where is retry?',answer:'In worker.py',answer_mode:'fallback',citations:[]}]} setAnswer={setAnswer} setQuestion={setQuestion} setPage={setPage}/>);
    fireEvent.click(screen.getByRole('button',{name:/Where is retry/}));
    expect(setAnswer).toHaveBeenCalledWith({answer:'In worker.py',answer_mode:'fallback',citations:[],retrieved_sources:[]});
    expect(setQuestion).toHaveBeenCalledWith('Where is retry?');
    expect(setPage).toHaveBeenCalledWith('assistant');
  });
});
