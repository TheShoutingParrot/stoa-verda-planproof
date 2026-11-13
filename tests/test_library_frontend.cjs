'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Node {
  constructor() {
    this.children = []; this.listeners = {}; this.attributes = {}; this.style = {}; this.dataset = {};
    this.value = ''; this.classList = {contains: () => false};
  }
  set textContent(t) { this.text = String(t); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(c => c.textContent).join(''); }
  setAttribute(k,v) { this.attributes[k] = String(v); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.text = ''; this.children = nodes; }
  add(n) { this.append(n); }
  addEventListener(type, f) { this.listeners[type] = f; }
  querySelector() { return null; }
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const scan = 'data/cubicasa5k/example.png';
const original = {question:'How many doors?',status:'answered',answer:2,image_sha256:'verified',evidence:[
  {label:'Door A',box:[100,100,200,200]}, {label:'Door B',box:[200,210,250,240]}]};
function harness(file, url, respond) {
  const nodes = new Map(), calls = [];
  const elm = id => {if(!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id);};
  const document={getElementById:elm, createElement:() => new Node(), createTextNode:text => {const n=new Node();n.textContent=text;return n;}};
  const context = vm.createContext({document, console, URL,URLSearchParams,AbortController,
    setTimeout,clearTimeout,Intl, window:{location:new URL(url,'https://example.invalid'),addEventListener(){}},
    history:{replaceState(){}},Option:class extends Node {constructor(text,val){super();this.textContent=text;this.value=val;}},
    fetch:async (u,opts) => {calls.push([u,opts]);return {ok:true,json:() => respond(u,opts)};}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'..','public',file),'utf8'),context);
  return {elm,calls,run:code=>vm.runInContext(code,context)};
}
function scanHarness(configured, remote) {
  return harness('library-scan.js','/scan-drawing.html?'+new URLSearchParams({path:scan}),(u,opts) => {
    if(opts?.method==='POST')return remote();
    return {imageSha256:'verified',configured,drawing:{path:scan,kind:'scan',name:'example.png'},saved:[original,
      {question:'How many lifts?',status:'answered',answer:0,image_sha256:'verified',evidence:[]},{question:'How many rooms?',status:'unknown',answer:null,image_sha256:'verified',evidence:[],reason:'Boundary unclear.'}]};
  });
}
test('scan selects boxes and replays positive, zero and unknown answers offline', async () => {
  const {elm,calls,run}=scanHarness(false);
  await flush();
  assert.equal(calls.length,1); assert.equal(elm('scan-answer').textContent,'2');
  assert.equal(elm('scan-overlay').children[0].style.left,'10%');
  elm('scan-evidence').children[1].listeners.click();
  assert.equal(elm('scan-overlay').children[1].attributes['aria-pressed'],'true');
  elm('scan-question').value='How many lifts?'; await run('ask()');
  assert.equal(elm('scan-answer').textContent,'0'); assert.equal(elm('scan-overlay').children.length,0);
  elm('scan-question').value='How many rooms?'; await run('ask()');
  assert.equal(elm('scan-answer').textContent,'Unknown'); assert.equal(elm('answer-reason').textContent,'Boundary unclear.');
  elm('scan-question').value='Count windows'; elm('scan-question').listeners.input();
  assert.equal(elm('scan-submit').disabled,true); assert.equal(calls.length,1);
});
test('hosted count only posts on explicit request and preserves a later saved selection', async () => {
  let finish;
  const {elm,calls,run}=scanHarness(true,()=>new Promise(resolve=>{finish=resolve;}));
  await flush(); assert.equal(calls.length,1);
  elm('scan-question').value='Count windows'; const asking=run('ask()'); await flush();
  assert.equal(calls.length,2); assert.equal(calls[1][1].headers['X-Planproof-Run'],'1');
  elm('saved-questions').listeners.change({target:{value:'1'}});
  finish({question:'Count windows',status:'answered',answer:1,image_sha256:'verified',evidence:[{label:'Window',box:[1,3,10,23]}],reused:false});
  await asking; assert.equal(elm('scan-answer').textContent,'0'); assert.equal(elm('saved-questions').children.length,4);
});
test('library links each drawing to its reader and ignores delayed obsolete searches', async () => {
  let deferFirst;
  const entries=[{kind:'swiss',path:'data/swiss_dwellings/site1_bldg2_floor3.pdf',name:'site1_bldg2_floor3.pdf'},
    {kind:'ifc',path:'data/ifc_models/house.ifc',name:'house.ifc'}, {kind:'scan',path:scan,name:'example.png'}];
  const {elm,run}=harness('library.js','/library.html',(u)=> u.includes('q=latest')?
    {available:true,total:3,drawings:entries}:new Promise(resolve=>{deferFirst=resolve;}));
  await flush(); elm('library-query').value='latest'; await run('search()');
  deferFirst({available:true,total:0,drawings:[]}); await flush();
  const urls=elm('library-list').children.map(li=>new URL(li.children[0].href,'https://example.invalid'));
  assert.deepEqual(urls.map(u=>u.pathname),['/','/model.html','/scan-drawing.html']);
  assert.deepEqual(urls.map(u=>u.searchParams.get('path')),entries.map(d=>d.path));
});
test('IFC reader exposes clickable source declarations and preserves measured square metres',async()=>{
  const path='data/ifc_models/house.ifc';
  const record = (id,name) => ({step_id:id,ifc_type:'IFCSPACE',global_id:'g'+id,name,storey:'First floor',
    relation_ids:[99],source_line:`#${id}=IFCSPACE(...);`,quantity_id:293,quantity_source_line:'#293=IFCQUANTITYAREA(...);',value:10.5});
  const drawing={kind:'ifc',name:'house.ifc',path};
  const {elm,run}=harness('model.js','/model.html?'+new URLSearchParams({path}),(u,opts) => opts?.method==='POST'
    ? {drawing,result:{status:'answered',answer:21,unit:'m2',method:'IFC space quantity',evidence:[record(41,'Office one'),record(42,'Office two')]}} : {drawing});
  await flush(); await run("ask('What is the area?')");
  assert.equal(elm('model-value').textContent,'21 m²');assert.match(elm('model-record').textContent,/#41=IFCSPACE/);
  elm('model-evidence').listeners.click({target:{closest:()=>({dataset:{index:'1'}})}});
  assert.match(elm('model-record').textContent,/#42=IFCSPACE/);assert.match(elm('model-record').textContent,/#293=IFCQUANTITYAREA/);
  assert.match(elm('model-record').textContent,/10.5 m²/);assert.equal(elm('record-ref').textContent,'#42');
});

test('a new pending or failed count has no old quantity or pins; saved and fresh answers require image digest', async () => {
  let finish;
  const {elm,run}=scanHarness(true,()=>new Promise(resolve=>{finish=resolve;}));
  await flush();
  elm('scan-question').value='Count windows'; const asking=run('ask()'); await flush();
  assert.equal(elm('scan-answer').textContent,'Pending'); assert.equal(elm('scan-overlay').children.length,0);
  assert.equal(elm('scan-evidence').children.length,0);
  finish({question:'Count windows',status:'answered',answer:0,evidence:[]}); await asking;
  assert.equal(elm('scan-answer').textContent,'Unavailable'); assert.equal(elm('scan-overlay').children.length,0);
  assert.equal(elm('saved-questions').children.length,3);
  run('delete reports[0].image_sha256; showReport(0)');
  assert.equal(elm('scan-answer').textContent,'Unknown'); assert.equal(elm('scan-overlay').children.length,0);
});
