"""Corvi's polished local desktop UI.

Run: python3 corvi_webapp.py
The app opens in the default browser and talks only to local Ollama.
"""
from __future__ import annotations

import json
import argparse
import difflib
import threading
import webbrowser
import subprocess
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import kit
from corvi_council import deliberate
from corvi_store import Store
from corvi_ext import load_skills, load_plugins, mcp_servers, mcp_list_tools

CFG = kit.Cfg("http://localhost:11434/v1", "ollama", "auto")
MODELS = []
STORE = Store()
PERMISSIONS = {"edit_file": "ask", "write_file": "ask", "run_bash": "ask", "mcp": "ask"}
ACTIVE_WORKSPACE = Path.cwd().resolve()
INTEGRATION_DISABLED = set()

HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Corvi</title>
<style>
:root{--bg:#18213b;--side:#111a32;--panel:#202b4d;--soft:#2b3963;--text:#f5e6c8;--muted:#b8c0d2;--blue:#4d7cff;--gold:#ffd166;--line:#465889}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;height:100vh;display:flex;overflow:hidden}
button{font:inherit;color:inherit;border:0;background:transparent;cursor:pointer} .app{display:flex;width:100%;height:100%}
.rail{width:68px;background:#151515;border-right:1px solid #292929;display:flex;flex-direction:column;align-items:center;padding:16px 10px;gap:18px}.logo{width:42px;height:42px;border-radius:13px;background:#fff;color:#181818;display:grid;place-items:center;font-size:22px;font-weight:800}.rail button{width:42px;height:42px;border-radius:12px;color:#a7a7a7;font-size:20px}.rail button:hover,.rail .active{background:#303030;color:#fff}.avatar{margin-top:auto;width:30px;height:30px;border-radius:50%;background:#36a269;display:grid;place-items:center;font-size:12px}
.sidebar{width:318px;background:var(--side);padding:18px 16px;display:flex;flex-direction:column}.brand{font-size:19px;font-weight:650;margin:2px 8px 25px;text-align:left}.brand span{color:#a8a8a8;font-size:20px}.brand:hover{color:#fff}.menu{position:absolute;top:58px;left:78px;background:#303030;border:1px solid #4a4a4a;border-radius:10px;padding:6px;z-index:5;box-shadow:0 12px 30px #0008}.menu button{display:block;width:190px;text-align:left;padding:9px;border-radius:7px}.menu button:hover{background:#444}.new{background:#333;border-radius:10px;padding:12px 14px;text-align:left;margin-bottom:25px}.new:hover{background:#3c3c3c}.section{color:#858585;font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin:16px 10px 8px}.chatlist{overflow:auto}.chatitem{padding:10px 11px;border-radius:9px;color:#d6d6d6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.chatitem:hover,.chatitem.selected{background:#393939}.project{color:#aaa;font-size:12px;padding:8px 10px;line-height:1.4;word-break:break-word}.bottom{margin-top:auto;border-top:1px solid var(--line);padding-top:14px;color:#aaa;font-size:12px}.profile{position:absolute;bottom:70px;left:78px;background:#303030;border:1px solid #4a4a4a;border-radius:10px;padding:14px;width:210px;z-index:5;box-shadow:0 12px 30px #0008}.profile strong{display:block;margin-bottom:5px}.profile small{color:#aaa}
.main{flex:1;min-width:0;display:flex;flex-direction:column}.top{height:58px;border-bottom:1px solid #292929;display:flex;align-items:center;padding:0 30px;gap:12px}.title{font-size:16px;font-weight:550;flex:1}.top select{background:var(--soft);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 30px 8px 10px}.top .council{color:#bcbcbc;display:flex;gap:7px;align-items:center}.top input{accent-color:var(--blue)}
.conversation{flex:1;overflow:auto;padding:36px max(30px,calc((100% - 920px)/2));}.welcome{text-align:center;margin:16vh auto 0;max-width:620px}.welcome h1{font-size:30px;font-weight:550;margin:0 0 12px}.welcome p{color:var(--muted);font-size:16px}.msg{margin:0 0 30px;display:flex;gap:13px;line-height:1.6}.msg.user{justify-content:flex-end}.bubble{max-width:78%;padding:12px 16px;border-radius:18px;white-space:pre-wrap}.user .bubble{background:#245ab4;border-bottom-right-radius:5px}.assistant .bubble{background:transparent;padding-left:0;max-width:88%}.who{width:30px;height:30px;border-radius:50%;background:#fff;color:#222;display:grid;place-items:center;font-weight:800;flex:none}.user .who{display:none}.code{background:#252525;border:1px solid #3a3a3a;border-radius:12px;margin-top:12px;padding:14px;font:12px ui-monospace,monospace;color:#b9e7c7;white-space:pre-wrap;overflow:auto}.activity{background:#202b4d;border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:0 0 12px;color:#c8d0e2;font-size:12px}.activity.running{border-color:var(--gold);color:var(--gold)}.activity.error,.activity.failed{border-color:#a95b65;color:#ff9ca4}.activity summary{cursor:pointer;font-weight:600}.activity pre{white-space:pre-wrap;max-height:220px;overflow:auto;color:#b9e7c7;margin:8px 0 0;font:12px ui-monospace,monospace}.composer-wrap{padding:12px max(30px,calc((100% - 920px)/2)) 22px}.composer{background:#303030;border:1px solid #444;border-radius:18px;padding:13px 15px 10px;box-shadow:0 4px 18px #0005}.composer textarea{width:100%;min-height:44px;max-height:180px;resize:none;border:0;outline:0;background:transparent;color:var(--text);font:15px inherit}.composer-row{display:flex;align-items:center;color:#aaa;gap:14px}.composer-row .spacer{flex:1}.send{width:32px;height:32px;border-radius:50%;background:var(--blue);display:grid;place-items:center;font-size:18px}.send:hover{background:#4781e4}.hint{font-size:12px;color:#777}.right{width:260px;background:#242424;margin:12px 12px 12px 0;border-radius:15px;padding:18px;display:none;overflow:auto}.right h3{font-size:15px;margin:0 0 16px}.right p{color:#888;font-size:13px}.panel-action{float:right;color:var(--gold);font-size:18px}.review-card{background:#303030;border:1px solid #444;border-radius:10px;padding:10px;margin:8px 0;font-size:12px}.review-card button{background:var(--blue);border-radius:6px;padding:5px 8px;margin:8px 5px 0 0}.review-empty{color:#777;font-size:12px}.status{font-size:12px;color:#777;padding:0 4px}
@media(min-width:1150px){.right{display:block}}@media(max-width:800px){.sidebar{display:none}.rail{width:54px}.conversation,.composer-wrap{padding-left:16px;padding-right:16px}}
</style></head><body><div class="app"><aside class="rail"><button class="active">⌂</button><button>▧</button><button>◷</button><button>⚙</button><button class="avatar" onclick="toggleProfile()">A</button><div id="profile" class="profile" hidden><strong>Abdul</strong><small>Local Corvi workspace<br>Ollama · HDD models</small></div></aside>
<aside class="sidebar"><button class="brand" onclick="toggleMenu()">Corvi <span>⌄</span></button><div id="workspaceMenu" class="menu" hidden><button onclick="newChat();toggleMenu()">New workspace</button><button onclick="openSettings();toggleMenu()">Permissions settings</button><button onclick="toggleMenu()">Close menu</button></div><button class="new" onclick="newChat()">＋ &nbsp; New chat</button><div class="section">Recent</div><div class="chatlist" id="chatlist"><div class="chatitem selected">Current conversation</div></div><div class="section">Projects</div><button class="project" onclick="chooseWorkspace()">⌂ &nbsp; <span id="project">Current workspace</span></button><div class="bottom">Local-first · Ollama<br>Models stay on your computer</div></aside>
<main class="main"><header class="top"><div class="title">New chat</div><select id="model" aria-label="Model"><option>auto</option></select><label class="council"><input id="council" type="checkbox"> Council</label></header><section class="conversation" id="conversation"><div class="welcome"><h1>How can I help?</h1><p>Ask Corvi to explain, build, debug, or improve your project.</p></div></section><div class="composer-wrap"><div class="composer"><textarea id="prompt" placeholder="Message Corvi…" rows="1"></textarea><div class="composer-row"><button onclick="status.textContent='Attachments are available through the project workspace'">＋</button><span class="hint">Local model · safe project assistance</span><span class="spacer"></span><span class="status" id="status">Connecting…</span><button class="send" onclick="send()">↑</button></div></div></div></main><aside class="right"><h3>Review <button class="panel-action" onclick="loadReview()">↻</button></h3><div id="reviewList" class="review-empty">No pending approvals or file changes.</div><hr style="border-color:#465889;border-width:1px 0 0"><h3 style="margin-top:24px">Outputs <button class="panel-action" onclick="status.textContent='Output panel ready'">＋</button></h3><p>Create an output</p><hr style="border-color:#465889;border-width:1px 0 0"><h3 style="margin-top:24px">Sources <button class="panel-action" onclick="status.textContent='Sources panel ready'">＋</button></h3><p>Sources will appear here when research is used.</p></aside></div>
<script>
const conv=document.getElementById('conversation'), promptBox=document.getElementById('prompt'), status=document.getElementById('status');document.querySelector('.app').classList.add('greeting');document.querySelector('.title').textContent='New chat';
const greetingStyle=document.createElement('style');greetingStyle.textContent='.greeting .rail,.greeting .sidebar,.greeting .top,.greeting .right{display:none}.greeting .main{width:100%}.greeting .conversation{display:flex;align-items:center;justify-content:center;padding:0}.greeting .welcome{margin:0 0 110px}.greeting .welcome h1{font-size:30px;font-weight:400}.greeting .welcome p{display:none}.greeting .composer-wrap{position:absolute;left:50%;bottom:26%;transform:translateX(-50%);width:min(720px,calc(100% - 40px));padding:0}.greeting .composer{border-radius:28px}';document.head.appendChild(greetingStyle);
let currentTaskId=null, streamController=null;
function add(role,text){let m=document.createElement('div');m.className='msg '+role; if(role==='assistant'){m.innerHTML='<div class="who">C</div><div class="bubble"></div>'}else m.innerHTML='<div class="bubble"></div>';m.querySelector('.bubble').textContent=text;conv.appendChild(m);conv.scrollTop=conv.scrollHeight;return m.querySelector('.bubble')}
function activity(text,kind='',detail=''){let el=document.createElement('details');el.className='activity '+kind;let summary=document.createElement('summary');summary.textContent=text;el.appendChild(summary);if(detail){let pre=document.createElement('pre');pre.textContent=detail;el.appendChild(pre)}conv.appendChild(el);conv.scrollTop=conv.scrollHeight;if(window.setPetState)setPetState(kind||'ready');return el}
function newChat(){currentTaskId=null;document.querySelector('.app').classList.add('greeting');conv.innerHTML='<div class="welcome"><h1>Ready when you are.</h1><p>Ask Corvi to explain, build, debug, or improve your project.</p></div>';document.querySelector('.title').textContent='New chat';document.querySelectorAll('.chatitem').forEach(x=>x.classList.remove('selected'));status.textContent='New chat';promptBox.focus()}
async function selectChat(el){document.querySelectorAll('.chatitem').forEach(x=>x.classList.remove('selected'));el.classList.add('selected');currentTaskId=el.dataset.id;document.querySelector('.app').classList.remove('greeting');document.querySelector('.title').textContent=el.textContent;conv.innerHTML='';status.textContent='Loading conversation…';try{let r=await fetch('/api/tasks/'+currentTaskId);let d=await r.json();d.messages.forEach(x=>add(x.role==='user'?'user':'assistant',x.content));(d.activities||[]).forEach(x=>activity(x.title+' · '+x.status,x.status==='failed'?'error':x.status,x.detail||''));loadPanels();status.textContent='Conversation restored';}catch(e){status.textContent='Could not restore conversation';}}
async function loadTasks(){try{let r=await fetch('/api/tasks');let d=await r.json();let list=document.getElementById('chatlist');list.innerHTML='';if(!d.tasks.length){let empty=document.createElement('div');empty.className='project';empty.textContent='No saved chats yet';list.appendChild(empty);return}let pinned=d.tasks.filter(t=>t.pinned);if(pinned.length){let label=document.createElement('div');label.className='section';label.textContent='Pinned';list.appendChild(label);pinned.forEach(t=>addTaskButton(t,list))}let recent=document.createElement('div');recent.className='section';recent.textContent='Recent';list.appendChild(recent);d.tasks.filter(t=>!t.pinned).forEach(t=>addTaskButton(t,list));}catch(e){status.textContent='Task history unavailable';}}
function addTaskButton(t,list){let el=document.createElement('button');el.className='chatitem';el.dataset.id=t.id;el.textContent=t.title;el.onclick=()=>selectChat(el);list.appendChild(el)}
async function searchTasks(){let q=window.prompt('Search saved tasks');if(q===null)return;let r=await fetch('/api/tasks/search?q='+encodeURIComponent(q));let d=await r.json();let list=document.getElementById('chatlist');list.innerHTML='';d.tasks.forEach(t=>{let el=document.createElement('button');el.className='chatitem';el.dataset.id=t.id;el.textContent=t.title;el.onclick=()=>selectChat(el);list.appendChild(el)});status.textContent=d.tasks.length+' task(s) found'}
async function taskAction(action){if(!currentTaskId){status.textContent='Select a task first';return}let body=action==='rename'?{title:window.prompt('New task name')}:action==='pin'?{pinned:1}:action==='archive'?{status:'archived'}:{};if(!Object.keys(body).length)return;await fetch('/api/tasks/'+currentTaskId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});loadTasks();status.textContent='Task updated'}
async function applyWorkspace(path){let r=await fetch('/api/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});let d=await r.json();if(d.path){currentTaskId=null;document.getElementById('project').textContent=d.name;document.querySelector('.title').textContent='New chat';document.querySelector('.app').classList.add('greeting');conv.innerHTML='<div class="welcome"><h1>How can I help?</h1><p>Workspace changed to '+d.name+'.</p></div>';status.textContent='Workspace selected: '+d.path;loadTasks()}else status.textContent=d.error||'Workspace selection failed';}window.corviNativeWorkspace=applyWorkspace;
async function switchWorkspace(){let r=await fetch('/api/workspaces');let d=await r.json();let options=(d.workspaces||[]).map(x=>x.name+' — '+x.path).join('\n');let choice=window.prompt('Saved workspaces:\n'+(options||'None')+'\n\nEnter a full folder path to switch or add one.');if(choice)applyWorkspace(choice.split(' — ').pop());}
async function chooseWorkspace(){if(window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.workspace){window.webkit.messageHandlers.workspace.postMessage('choose');return}let path=window.prompt('Enter a project folder path',location.pathname);if(path)applyWorkspace(path);}
async function openSettings(){let r=await fetch('/api/settings/permissions');let d=await r.json();let panel=document.createElement('div');panel.style.cssText='position:fixed;inset:0;background:#0009;display:grid;place-items:center;z-index:30';let card=document.createElement('div');card.style.cssText='width:min(420px,calc(100% - 32px));background:#202b4d;border:1px solid #465889;border-radius:14px;padding:22px;box-shadow:0 18px 50px #0009;color:#f5e6c8';card.innerHTML='<h2>Permissions</h2><p>Choose how Corvi handles actions.</p><div id="permissionFields"></div><button id="savePermissions">Save</button><button id="closePermissions">Close</button>';panel.appendChild(card);document.body.appendChild(panel);let fields=card.querySelector('#permissionFields');Object.entries(d.permissions).forEach(([name,value])=>{let row=document.createElement('label');row.style.cssText='display:flex;justify-content:space-between;padding:10px 0';row.textContent=name;let select=document.createElement('select');select.style.cssText='background:#2b3963;color:#f5e6c8;padding:6px';['ask','allow','deny'].forEach(x=>{let o=document.createElement('option');o.value=x;o.textContent=x;o.selected=x===value;select.appendChild(o)});select.dataset.name=name;row.appendChild(select);fields.appendChild(row)});card.querySelector('#savePermissions').onclick=async()=>{let permissions={};fields.querySelectorAll('select').forEach(x=>permissions[x.dataset.name]=x.value);await fetch('/api/settings/permissions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({permissions})});panel.remove();status.textContent='Permissions saved'};card.querySelector('#closePermissions').onclick=()=>panel.remove();}
async function openIntegrations(){let r=await fetch('/api/integrations');let d=await r.json();let summary=(d.mcp||[]).map(x=>x.name+': '+(x.enabled?'enabled':'disabled')+' ['+(x.tools||[]).join(', ')+']').join('\n')||'No MCP servers configured';let choice=window.prompt('MCP servers and tools:\n'+summary+'\n\nType a server name to toggle it, or cancel.');if(!choice)return;let item=(d.mcp||[]).find(x=>x.name===choice);if(item){await fetch('/api/integrations/mcp/'+encodeURIComponent(choice),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!item.enabled})});status.textContent='MCP '+choice+' '+(!item.enabled?'enabled':'disabled')}else status.textContent='No matching MCP server';}
async function openIntegrationPanel(){let r=await fetch('/api/integrations');let d=await r.json();let text=(d.mcp||[]).map(x=>'MCP · '+x.name+' · '+(x.enabled?'enabled':'disabled')+' · '+(x.tools||[]).join(', ')).concat((d.skills||[]).map(x=>'Skill · '+x.name)).concat((d.plugins||[]).map(x=>'Plugin · '+x.name)).join('\n')||'No integrations found';window.alert(text);}
async function showIntegrations(){let r=await fetch('/api/integrations');let d=await r.json();let panel=document.createElement('div');panel.style.cssText='position:fixed;inset:0;background:#0009;display:grid;place-items:center;z-index:30';let card=document.createElement('div');card.style.cssText='width:min(620px,calc(100% - 32px));max-height:80vh;overflow:auto;background:#202b4d;border:1px solid #465889;border-radius:14px;padding:22px;color:#f5e6c8';card.innerHTML='<h2>Integrations</h2><div id="integrationRows"></div><button id="closeIntegrations">Close</button>';panel.appendChild(card);document.body.appendChild(panel);let rows=card.querySelector('#integrationRows');(d.mcp||[]).forEach(x=>{let row=document.createElement('div');row.style.cssText='padding:12px;border-bottom:1px solid #465889';row.innerHTML='<strong>MCP · '+x.name+'</strong><br><small>'+(x.tools||[]).join(', ')+'</small> <button>'+(x.enabled?'Disable':'Enable')+'</button>';row.querySelector('button').onclick=async()=>{await fetch('/api/integrations/mcp/'+encodeURIComponent(x.name),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!x.enabled})});panel.remove();showIntegrations()};rows.appendChild(row)});(d.skills||[]).concat(d.plugins||[]).forEach(x=>{let row=document.createElement('div');row.style.cssText='padding:10px;border-bottom:1px solid #465889';row.textContent=(x.path.includes('skills')?'Skill · ':'Plugin · ')+x.name+' · loaded';rows.appendChild(row)});card.querySelector('#closeIntegrations').onclick=()=>panel.remove();}
async function loadPanels(){if(!currentTaskId)return;let r=await fetch('/api/panels?task_id='+encodeURIComponent(currentTaskId));let d=await r.json();let panel=document.querySelector('.right');let out=document.getElementById('outputsList')||document.createElement('div');out.id='outputsList';out.className='review-empty';out.innerHTML=d.outputs.length?d.outputs.map(x=>'<button class="review-card" style="display:block;width:100%;text-align:left" onclick="window.open(\''+x.path_or_url+'\',\'_blank\')">'+x.title+'<br><small>'+x.path_or_url+'</small></button>').join(''):'No outputs yet';let src=document.getElementById('sourcesList')||document.createElement('div');src.id='sourcesList';src.className='review-empty';src.innerHTML=d.sources.length?d.sources.map(x=>'<button class="review-card" style="display:block;width:100%;text-align:left" onclick="window.open(\''+x.path_or_url+'\',\'_blank\')">'+x.title+'<br><small>'+x.path_or_url+'</small></button>').join(''):'No sources yet';if(!out.parentNode)panel.appendChild(out);if(!src.parentNode){let h=document.createElement('h3');h.textContent='Sources';panel.appendChild(h);panel.appendChild(src);}}
function petSettings(){let size=window.prompt('Pet size in pixels',localStorage.getItem('corvi-pet-size')||'120');let position=window.prompt('Pet position: right,bottom',localStorage.getItem('corvi-pet-position')||'24,20');if(size){localStorage.setItem('corvi-pet-size',size);pet.style.width=size+'px';pet.style.height=size+'px'}if(position){let [right,bottom]=position.split(',');pet.style.right=right+'px';pet.style.bottom=bottom+'px';localStorage.setItem('corvi-pet-position',position)}status.textContent='Pet settings saved'}
async function research(){let q=window.prompt('Research query');if(!q||!currentTaskId){status.textContent='Open a task before researching';return}let r=await fetch('/api/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:currentTaskId,query:q})});let d=await r.json();status.textContent=d.error||'Sources updated';loadPanels();}
async function loadReview(){let box=document.getElementById('reviewList');if(!currentTaskId){box.textContent='Select a saved task to review its actions.';return}try{let r=await fetch('/api/review?task_id='+encodeURIComponent(currentTaskId));let d=await r.json();box.innerHTML='';if(!d.approvals.length){box.textContent='No pending approvals or file changes.';box.className='review-empty';return}d.approvals.filter(x=>x.decision==='pending').forEach(x=>{let card=document.createElement('div');card.className='review-card';card.innerHTML='<strong>'+x.action_type+'</strong><br>'+x.summary+(x.diff?'<pre class="code">'+x.diff.replace(/</g,'&lt;')+'</pre>':'')+'<br><button>Approve</button><button>Deny</button><button>Retry</button>';card.querySelectorAll('button')[0].onclick=()=>decideReview(x.id,'approved',card);card.querySelectorAll('button')[1].onclick=()=>decideReview(x.id,'denied',card);card.querySelectorAll('button')[2].onclick=()=>decideReview(x.id,'retry',card);box.appendChild(card)});if(!box.children.length)box.textContent='No pending approvals or file changes.'}catch(e){box.textContent='Review data unavailable';}}
async function decideReview(id,decision,card){let r=await fetch('/api/review/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision})});let d=await r.json();card.remove();status.textContent=decision==='approved'?(d.ok?'Action executed':'Action failed'):decision==='retry'?'New approval created':'Action denied';loadReview();loadTasks();}
function toggleMenu(){let m=document.getElementById('workspaceMenu');m.hidden=!m.hidden;status.textContent=m.hidden?'Ready':'Workspace menu open';}
let workspaceSwitch=document.createElement('button');workspaceSwitch.className='project';workspaceSwitch.textContent='⇄  Switch workspace';workspaceSwitch.onclick=switchWorkspace;document.querySelector('.sidebar').insertBefore(workspaceSwitch,document.querySelector('.bottom'));let integrationButton=document.createElement('button');integrationButton.className='project';integrationButton.textContent='⚙ Integrations';integrationButton.onclick=openIntegrationPanel;document.querySelector('.sidebar').insertBefore(integrationButton,document.querySelector('.bottom'));let petButton=document.createElement('button');petButton.className='project';petButton.textContent='♣ Pet settings';petButton.onclick=petSettings;document.querySelector('.sidebar').insertBefore(petButton,document.querySelector('.bottom'));
let taskTools=document.createElement('div');taskTools.innerHTML='<button class="project">⌕ Search</button><button class="project">☆ Pin</button><button class="project">✎ Rename</button><button class="project">Archive</button>';let tb=taskTools.querySelectorAll('button');tb[0].onclick=searchTasks;tb[1].onclick=()=>taskAction('pin');tb[2].onclick=()=>taskAction('rename');tb[3].onclick=()=>taskAction('archive');document.querySelector('.sidebar').insertBefore(taskTools,workspaceSwitch);
function toggleProfile(){let p=document.getElementById('profile');p.hidden=!p.hidden;status.textContent=p.hidden?'Ready':'Profile panel open';}
async function load(){let r=await fetch('/api/models');let d=await r.json();let s=document.getElementById('model');d.models.forEach(x=>{let o=document.createElement('option');o.textContent=x;s.appendChild(o)});status.textContent=d.models.length+' local model(s) ready'}
async function send(){if(streamController){streamController.abort();streamController=null;status.textContent='Cancelled';activity('Stream cancelled','error');return}let p=promptBox.value.trim();if(!p)return;document.querySelector('.app').classList.remove('greeting');document.querySelector('.title').textContent=p.slice(0,48);promptBox.value='';add('user',p);activity('Streaming from local model…','running');status.textContent='Working…';let a=add('assistant','');streamController=new AbortController();try{let r=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},signal:streamController.signal,body:JSON.stringify({prompt:p,model:document.getElementById('model').value,task_id:currentTaskId})});let reader=r.body.getReader(),decoder=new TextDecoder(),buffer='';while(true){let part=await reader.read();if(part.done)break;buffer+=decoder.decode(part.value,{stream:true});let lines=buffer.split('\n');buffer=lines.pop();for(let line of lines){if(!line.trim())continue;let e=JSON.parse(line);if(e.type==='start')currentTaskId=e.task_id;if(e.type==='token'){a.textContent+=e.text;conv.scrollTop=conv.scrollHeight}if(e.type==='complete'){currentTaskId=e.task_id;(e.activities||[]).slice(-2).forEach(x=>activity(x.title+' · '+x.status,x.status==='failed'?'error':x.status,x.detail||''));status.textContent='Ready';}if(e.type==='error'){a.textContent='Ollama is not reachable: '+e.error;activity('Stream failed','error',e.error);status.textContent='Ollama unavailable';}}}streamController=null;loadTasks();}catch(e){streamController=null;if(e.name!=='AbortError'){a.textContent='Ollama is not reachable. Start Ollama with: ollama serve';activity('Stream failed','error',e.message);status.textContent='Ollama unavailable';}}}
document.querySelectorAll('.rail button:not(.avatar)').forEach(b=>b.onclick=()=>{document.querySelectorAll('.rail button').forEach(x=>x.classList.remove('active'));b.classList.add('active');status.textContent=b.textContent==='⌂'?'Home':'Section selected'});
document.querySelectorAll('button:not([onclick])').forEach(b=>b.onclick=()=>{status.textContent='This workspace control is ready';});
promptBox.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});load();loadTasks();setInterval(load,5000);setInterval(loadTasks,5000);
const pet=document.createElement('div');pet.id='corviPet';Object.assign(pet.style,{position:'fixed',right:'24px',bottom:'20px',width:'120px',height:'120px',backgroundImage:"url('/assets/corvi-crow-poses.png')",backgroundSize:'300% 300%',backgroundPosition:'50% 50%',backgroundRepeat:'no-repeat',filter:'drop-shadow(0 8px 8px #0008)',zIndex:'20',cursor:'pointer',transition:'transform .2s'});const petStates={running:'0% 0%',ready:'50% 0%',blocked:'100% 0%',needs_input:'0% 50%',error:'100% 50%',interrupted:'50% 100%'};function setPetState(state){pet.dataset.state=state;pet.style.backgroundPosition=petStates[state]||'50% 50%';pet.style.transform=state==='running'?'translateY(-4px) scale(1.03)':state==='error'||state==='blocked'?'rotate(-3deg)':state==='needs_input'?'translateY(2px)':'translateY(0)'}function togglePet(){let hidden=localStorage.getItem('corvi-pet-hidden')==='1';localStorage.setItem('corvi-pet-hidden',hidden?'0':'1');pet.hidden=!hidden;status.textContent=hidden?'Pet shown':'Pet hidden'}pet.title='Corvi mascot · double-click to hide';pet.onclick=()=>{status.textContent='Corvi is ready';setPetState('ready')};pet.ondblclick=togglePet;if(localStorage.getItem('corvi-pet-hidden')==='1')pet.hidden=true;if(window.matchMedia('(prefers-reduced-motion: reduce)').matches)pet.style.transition='none';document.body.appendChild(pet);
</script><script>openIntegrationPanel=showIntegrations;</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def _json(self, data, code=200):
        raw = json.dumps(data).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path == '/':
            raw = HTML.encode(); self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
        elif self.path == '/api/models': self._json({'models': MODELS})
        elif self.path == '/api/settings/permissions': self._json({'permissions': PERMISSIONS})
        elif self.path == '/api/workspace': self._json({'path': str(ACTIVE_WORKSPACE), 'name': ACTIVE_WORKSPACE.name})
        elif self.path == '/api/workspaces': self._json({'workspaces': STORE.workspaces()})
        elif self.path == '/api/tasks': self._json({'tasks': STORE.recent(ACTIVE_WORKSPACE)})
        elif urlparse(self.path).path == '/api/tasks/search': self._json({'tasks': STORE.search_tasks(ACTIVE_WORKSPACE, parse_qs(urlparse(self.path).query).get('q',[''])[0])})
        elif self.path.startswith('/api/panels'):
            task_id = parse_qs(urlparse(self.path).query).get('task_id', [''])[0]
            items = STORE.artifacts(task_id) if task_id else []
            self._json({'outputs':[x for x in items if x['kind'] in ('file','report','terminal','diff')], 'sources':[x for x in items if x['kind']=='source']})
        elif self.path == '/api/integrations':
            servers = mcp_servers(ACTIVE_WORKSPACE); mcp = []
            for name, spec in servers.items():
                tools = []
                if name not in INTEGRATION_DISABLED:
                    try: tools = [x.get('name') for x in mcp_list_tools(name, servers, ACTIVE_WORKSPACE) if x.get('name')]
                    except Exception as exc: tools = ['error: '+str(exc)]
                mcp.append({'name':name,'enabled':name not in INTEGRATION_DISABLED,'tools':tools})
            self._json({'mcp':mcp,'skills':[{'name':x.name,'path':str(x.path)} for x in load_skills(ACTIVE_WORKSPACE)],'plugins':[{'name':x.name,'path':str(x)} for x in load_plugins(ACTIVE_WORKSPACE)]})
        elif self.path.startswith('/api/review'):
            task_id = parse_qs(urlparse(self.path).query).get('task_id', [''])[0]
            approvals = STORE.approvals(task_id) if task_id else []
            for item in approvals:
                try:
                    args = json.loads(item.get('arguments_json') or '{}'); path = Path(args.get('path',''))
                    if item.get('action_type') == 'edit_file':
                        old = str(args.get('old_string','')).splitlines(True); new = str(args.get('new_string','')).splitlines(True)
                        item['diff'] = ''.join(difflib.unified_diff(old, new, fromfile=str(path)+' (before)', tofile=str(path)+' (after)'))
                    elif item.get('action_type') == 'write_file':
                        item['diff'] = ''.join(difflib.unified_diff([], str(args.get('content','')).splitlines(True), fromfile='/dev/null', tofile=str(path)))
                    if path.is_file() and item.get('action_type') in ('edit_file','write_file'):
                        actual = path.read_text(errors='replace').splitlines(True); proposed = str(args.get('new_string', args.get('content',''))).splitlines(True)
                        item['current_diff'] = ''.join(difflib.unified_diff(proposed, actual, fromfile=str(path)+' (proposed)', tofile=str(path)+' (current)'))
                except Exception: item['diff'] = ''
            self._json({'approvals': approvals})
        elif self.path.startswith('/api/tasks/'):
            task_id = self.path.rsplit('/', 1)[-1]; self._json({'messages': STORE.messages(task_id), 'activities': STORE.activities(task_id)})
        elif self.path == '/assets/corvi-crow-poses.png':
            path = Path(__file__).resolve().parent / 'assets' / 'corvi-crow-poses.png'
            if not path.is_file(): path = Path(__file__).resolve().parent / 'corvi-crow-poses.png'
            if not path.is_file(): return self.send_error(404)
            raw = path.read_bytes(); self.send_response(200); self.send_header('Content-Type','image/png'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
        else: self.send_error(404)
    def do_POST(self):
        global ACTIVE_WORKSPACE
        if self.path == '/api/command/stream':
            self._stream_command(); return
        if self.path == '/api/integrations/reload':
            return self._json({'ok':True})
        if self.path.startswith('/api/integrations/mcp/'):
            name = self.path.rsplit('/',1)[-1]
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); enabled = bool(body.get('enabled'))
                if name not in mcp_servers(ACTIVE_WORKSPACE): return self._json({'error':'MCP server not configured'}, 404)
                if enabled: INTEGRATION_DISABLED.discard(name)
                else: INTEGRATION_DISABLED.add(name)
                return self._json({'ok':True,'enabled':enabled})
            except Exception as exc: return self._json({'error':str(exc)},400)
        if self.path == '/api/chat/stream':
            self._stream_chat()
            return
        if self.path == '/api/settings/permissions':
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); PERMISSIONS.update({k:v for k,v in body.get('permissions',{}).items() if k in PERMISSIONS and v in ('ask','allow','deny')}); return self._json({'permissions':PERMISSIONS})
            except Exception as exc: return self._json({'error':str(exc)}, 400)
        if self.path.startswith('/api/tasks/') and self.path.count('/') >= 3:
            try:
                task_id = self.path.split('/')[3]; body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); STORE.update_task(task_id, **body); return self._json({'ok':True})
            except Exception as exc: return self._json({'error':str(exc)},400)
        if self.path == '/api/workspace':
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); path = Path(body.get('path','')).expanduser().resolve()
                if not path.is_dir(): return self._json({'error':'workspace folder does not exist'}, 400)
                ACTIVE_WORKSPACE = path
                return self._json({'path':str(path), 'name':path.name})
            except Exception as exc: return self._json({'error':str(exc)}, 400)
        if self.path == '/api/research':
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); task_id, query = body.get('task_id'), body.get('query','')
                results = kit.t_web_search(query, 5)
                if results.startswith('Error'): return self._json({'error':results}, 502)
                for line in results.split('\n'):
                    if line.startswith('URL: '): STORE.add_artifact(task_id, 'source', query, line[5:].strip())
                return self._json({'ok':True, 'text':results})
            except Exception as exc: return self._json({'error':str(exc)}, 500)
        if self.path.startswith('/api/review/'):
            try:
                approval_id = self.path.rsplit('/', 1)[-1]; body = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); decision = body.get('decision'); item = STORE.approval(approval_id)
                if decision not in ('approved', 'denied', 'retry'): return self._json({'error':'invalid decision'}, 400)
                if not item: return self._json({'error':'approval not found'}, 404)
                if decision == 'retry':
                    new_id = STORE.retry_approval(approval_id, body.get('feedback','')); return self._json({'ok':True, 'approval_id':new_id, 'status':'pending'})
                STORE.decide_approval(approval_id, decision, body.get('feedback',''))
                if decision == 'approved':
                    args = json.loads(item.get('arguments_json') or '{}'); name = item['action_type']; result = kit.TOOL_FUNCS.get(name, lambda **_: 'Error: unsupported approved action')(**args)
                    ok = not str(result).startswith('Error')
                    detail = str(result); exit_code = ''
                    if name == 'run_bash':
                        import re
                        match = re.search(r'exit code (-?\d+)', detail); exit_code = (' · exit code '+match.group(1)) if match else ''
                    title = name+(' completed' if ok else ' failed')+exit_code
                    if name == 'run_bash' and any(word in str(args.get('command','')).lower() for word in ('test','pytest','unittest')): title += ' · test summary'
                    STORE.add_activity(item['run_id'], 'edit' if name in ('edit_file','write_file') else 'command', title, detail[:2000], 'success' if ok else 'failed')
                    STORE.finish_run(item['run_id'], item['task_id'], 'ready' if ok else 'error', None if ok else str(result))
                    STORE.add_message(item['task_id'], 'tool', str(result), name)
                    return self._json({'ok':ok, 'result':result, 'status':'ready' if ok else 'error'})
                STORE.add_activity(item['run_id'], 'status', 'Action denied', body.get('feedback',''), 'failed'); STORE.finish_run(item['run_id'], item['task_id'], 'blocked', body.get('feedback',''))
                return self._json({'ok':True, 'status':'blocked'})
            except Exception as exc: return self._json({'error':str(exc)}, 500)
        if self.path != '/api/chat': return self.send_error(404)
        try:
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); prompt=body.get('prompt',''); selected=body.get('model','auto')
            task_id = body.get('task_id')
            if not task_id: task_id = STORE.create_task(Path.cwd(), prompt, selected)["id"]
            STORE.add_message(task_id, 'user', prompt, selected)
            run_id = STORE.start_run(task_id, selected); STORE.add_activity(run_id, 'status', 'Started local run', selected, 'running')
            kit.ensure_ollama(CFG)
            if not MODELS:
                try:
                    MODELS.extend(kit.list_models(CFG, timeout=8))
                except Exception:
                    STORE.add_activity(run_id, 'status', 'Ollama unavailable', 'Start the local Ollama service.', 'failed'); STORE.finish_run(run_id, task_id, 'error', 'Ollama unavailable')
                    return self._json({'text':'Ollama is unavailable. Start it with: ollama serve'}, 503)
            pending_review = False
            if body.get('council') and len(MODELS)>=2: text, _ = deliberate(CFG.base_url, CFG.api_key, MODELS, prompt)
            else:
                model=kit.choose_model(CFG,prompt,MODELS) if selected=='auto' else selected; parts=[]
                coding = any(word in prompt.lower() for word in ('edit', 'write', 'create file', 'run ', 'command', 'code', 'debug'))
                text, calls = kit.stream_chat(kit.Cfg(CFG.base_url,CFG.api_key,model),[{'role':'user','content':prompt}],parts.append,use_tools=coding)
                if calls:
                    for call in calls:
                        name, args = call.get('name','external'), call.get('arguments') or {}
                        target = str(args.get('path') or args.get('command') or 'workspace')
                        summary = f"{name} requested for {target}"
                        STORE.create_approval(run_id, name if name in ('write_file','edit_file','run_bash') else 'external', target, summary, args)
                        STORE.add_activity(run_id, 'edit' if name in ('edit_file','write_file') else 'command', 'Waiting for approval: '+name, json.dumps(args, ensure_ascii=False), 'waiting')
                    STORE.add_activity(run_id, 'status', 'Waiting for approval', f'{len(calls)} action(s) require review.', 'waiting'); STORE.finish_run(run_id, task_id, 'needs_input'); pending_review = True
                    text = 'I prepared an action for review. Approve or deny it in the Review panel before anything changes.'
                else:
                    text = text or ''.join(parts) or '(No response returned.)'
            if not pending_review:
                STORE.add_activity(run_id, 'message', 'Model response completed', selected, 'success'); STORE.finish_run(run_id, task_id, 'ready')
            STORE.add_message(task_id, 'assistant', text, selected)
            self._json({'text':text, 'task_id':task_id, 'activities': STORE.activities(task_id)})
        except Exception as exc:
            if 'run_id' in locals() and 'task_id' in locals():
                STORE.add_activity(run_id, 'status', 'Run failed', str(exc), 'failed'); STORE.finish_run(run_id, task_id, 'error', str(exc))
            self._json({'text':'Error: '+str(exc)},500)
    def log_message(self,*args): pass

    def _stream_chat(self):
        """Stream newline-delimited JSON events to the WebKit client."""
        run_id = task_id = None
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); prompt = body.get('prompt',''); selected = body.get('model','auto')
            task_id = body.get('task_id') or STORE.create_task(Path.cwd(), prompt, selected)['id']
            STORE.add_message(task_id, 'user', prompt, selected); run_id = STORE.start_run(task_id, selected)
            self.send_response(200); self.send_header('Content-Type','application/x-ndjson; charset=utf-8'); self.send_header('Cache-Control','no-cache'); self.send_header('Connection','close'); self.end_headers()
            def emit(event):
                self.wfile.write((json.dumps(event, ensure_ascii=False) + '\n').encode()); self.wfile.flush()
            emit({'type':'start','task_id':task_id,'status':'running'}); STORE.add_activity(run_id, 'status', 'Streaming response started', selected, 'running')
            kit.ensure_ollama(CFG)
            global MODELS
            if not MODELS: MODELS = kit.list_models(CFG, timeout=8)
            model = kit.choose_model(CFG, prompt, MODELS) if selected == 'auto' else selected
            parts=[]
            def on_text(chunk):
                parts.append(chunk); emit({'type':'token','text':chunk})
            text, calls = kit.stream_chat(kit.Cfg(CFG.base_url, CFG.api_key, model), [{'role':'user','content':prompt}], on_text, use_tools=False)
            text = ''.join(parts) or text or '(No response returned.)'
            STORE.add_message(task_id, 'assistant', text, selected); STORE.add_activity(run_id, 'message', 'Streaming response completed', selected, 'success'); STORE.finish_run(run_id, task_id, 'ready')
            emit({'type':'complete','task_id':task_id,'status':'ready','text':text,'activities':STORE.activities(task_id)})
        except (BrokenPipeError, ConnectionResetError):
            if run_id and task_id: STORE.add_activity(run_id, 'status', 'Stream cancelled', 'Client disconnected.', 'failed'); STORE.finish_run(run_id, task_id, 'interrupted', 'Client disconnected')
        except Exception as exc:
            if run_id and task_id: STORE.add_activity(run_id, 'status', 'Streaming failed', str(exc), 'failed'); STORE.finish_run(run_id, task_id, 'error', str(exc))
            try: self.wfile.write((json.dumps({'type':'error','error':str(exc)})+'\n').encode()); self.wfile.flush()
            except Exception: pass

    def _stream_command(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); command = str(body.get('command','')).strip()
            if not command: return self._json({'error':'command is required'}, 400)
            self.send_response(200); self.send_header('Content-Type','application/x-ndjson; charset=utf-8'); self.send_header('Cache-Control','no-cache'); self.end_headers()
            def emit(event): self.wfile.write((json.dumps(event, ensure_ascii=False)+'\n').encode()); self.wfile.flush()
            emit({'type':'start','status':'running','command':command})
            proc = subprocess.Popen(command, cwd=str(ACTIVE_WORKSPACE), shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in proc.stdout or []: emit({'type':'output','text':line})
            code = proc.wait(); emit({'type':'complete','status':'ready' if code == 0 else 'error','exit_code':code,'summary':'passed' if code == 0 else 'failed'})
        except Exception as exc:
            try: self._json({'error':str(exc)}, 500)
            except Exception: pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    global MODELS
    # Do not block the desktop window while an HDD-backed Ollama service
    # starts. The page must be available immediately; model discovery can
    # finish in the background.
    MODELS=[]
    try: server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError: server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}'
    print(f'CORVI_URL={url}', flush=True)
    def warmup():
        global MODELS
        kit.ensure_ollama(CFG)
        try: MODELS = kit.list_models(CFG, timeout=8)
        except Exception: MODELS = []
    threading.Thread(target=warmup, daemon=True).start()
    if not args.serve: threading.Timer(.25,lambda:webbrowser.open(url)).start()
    server.serve_forever()

if __name__=='__main__': main()
