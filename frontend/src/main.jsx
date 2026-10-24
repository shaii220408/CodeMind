import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

const API='http://localhost:8000';
function App(){
 const [projects,setProjects]=useState([]),[project,setProject]=useState(null),[name,setName]=useState(''),[file,setFile]=useState(null),[status,setStatus]=useState('NOT_STARTED'),[question,setQuestion]=useState(''),[answer,setAnswer]=useState(null),[loading,setLoading]=useState(false),[overview,setOverview]=useState(null),[files,setFiles]=useState([]);
 const load=()=>fetch(API+'/api/projects').then(r=>r.json()).then(setProjects);
 useEffect(load,[]);
 const create=async()=>{let r=await fetch(API+'/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});let p=await r.json();setProjects(x=>[p,...x]);setProject(p);setName('');};
 const select=async p=>{setProject(p);setAnswer(null);let [o,f]=await Promise.all([fetch(`${API}/api/projects/${p.id}/overview`),fetch(`${API}/api/projects/${p.id}/files`)]);setOverview(await o.json());setFiles(await f.json());};
 const upload=async()=>{if(!file||!project)return;let fd=new FormData();fd.append('file',file);await fetch(`${API}/api/projects/${project.id}/upload`,{method:'POST',body:fd});setStatus('QUEUED');let timer=setInterval(async()=>{let s=await fetch(`${API}/api/projects/${project.id}/status`).then(r=>r.json());setStatus(s.status);if(['COMPLETED','FAILED'].includes(s.status)){clearInterval(timer);select(project)}},2000)};
 const ask=async()=>{if(!question||!project)return;setLoading(true);let r=await fetch(API+'/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:project.id,question})});setAnswer(await r.json());setLoading(false)};
 return <div className="app"><aside><div className="brand">⌘ Code<span>RAG</span></div><div className="sideTitle">PROJECTS</div>{projects.map(p=><button className={'project '+(project?.id===p.id?'active':'')} onClick={()=>select(p)} key={p.id}>{p.name}</button>)}<div className="new"><input value={name} onChange={e=>setName(e.target.value)} placeholder="New project"/><button onClick={create}>+</button></div></aside>
 <main><header><div><h1>{project?project.name:'Codebase Assistant'}</h1><p>{project?'Ask questions grounded in your repository.':'Create a project and upload a ZIP repository.'}</p></div>{project&&<div className="pill">● {status}</div>}</header>
 {!project?<section className="empty"><div className="heroIcon">⌁</div><h2>Your codebase, searchable by meaning.</h2><p>Create a project from the sidebar, then upload a repository ZIP.</p></section>:
 <><section className="stats">{[['Files',overview?.file_count??0],['Chunks',overview?.chunk_count??0],['Languages',overview?Object.keys(overview.languages).length:0],['Index',status]].map(([a,b])=><div className="card" key={a}><small>{a}</small><strong>{b}</strong></div>)}</section>
 <section className="upload"><div><b>Repository indexing</b><p>ZIP only · ignored: .git, node_modules, build, dist, .venv, __pycache__</p></div><input type="file" accept=".zip" onChange={e=>setFile(e.target.files[0])}/><button onClick={upload} disabled={!file||status==='PROCESSING'}>Index repository</button></section>
 <section className="chat"><div className="examples"><span>Try asking</span>{['Where is authentication implemented?','Explain the main service.','Where is retry logic implemented?','Explain the architecture of this repository.'].map(q=><button key={q} onClick={()=>setQuestion(q)}>{q}</button>)}</div><div className="ask"><textarea value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Ask anything about this codebase..."/><button onClick={ask}>{loading?'Thinking…':'Ask CodeRAG ↗'}</button></div>{answer&&<div className="result"><h3>Answer</h3><pre>{answer.answer}</pre><h3>Sources</h3>{answer.citations.map((c,i)=><div className="source" key={i}><b>{c.file}</b><span>{c.symbol} · lines {c.start_line}–{c.end_line}</span></div>)}</div>}</section>
 <section className="files"><h3>Indexed files</h3>{files.map(f=><div className="file" key={f.id}><span>{f.path}</span><small>{f.language}</small></div>)}</section></>}</main></div>
}
createRoot(document.getElementById('root')).render(<App/>);
