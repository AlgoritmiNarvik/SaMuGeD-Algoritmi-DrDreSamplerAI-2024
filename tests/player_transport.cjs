const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function transport(atlas){
 const html=fs.readFileSync(atlas?'scripts/top_phrases.html':'scripts/loop_player.html','utf8');
 const stop=html.match(/function stop\(.*\n/)[0];
 const start=html.indexOf(atlas?'async function play(r,':'async function play({');
 const end=html.indexOf('\n}',start)+2;
 const nodes=new Map(),pending=new Map(),sources=[];
 const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',value:'0.5'});return nodes.get(id)};
 class AudioContext{
  constructor(){this.currentTime=0;this.destination={};this.state="suspended"}
  async resume(){this.state="running";this.onstatechange?.()}
  createGain(){return {gain:{value:0},connect(){}}}
  async decodeAudioData(id){return {id,duration:2}}
  createBufferSource(){const source={connect(){},disconnect(){},start(){this.started=true},stop(){this.stopped=true}};sources.push(source);return source}
 }
 const box=vm.createContext({AudioContext,document:{getElementById:node,querySelectorAll:()=>[]},fetch:url=>new Promise(resolve=>pending.set(url,resolve))});
 vm.runInContext(`let selected={phrase_id:'a'}, context=null,ctx=null,gain=null,playing=null,wantsPlayback=false,request=0,token=0,started=0,position=null,playingUrl=null;
 const cache=new Map(),audioCache=new Map(),data={audio:{}},clean=x=>x;
 function audioId(){return selected.phrase_id}
 ${stop}\n${html.slice(start,end)}`,box);
 const choose=(id,replace=true)=>{
  if(atlas){vm.runInContext(`data.audio[${JSON.stringify(id)}]={wav:${JSON.stringify(id)}}`,box);return vm.runInContext(`play({phrase_id:${JSON.stringify(id)},title_from_path:${JSON.stringify(id)}},'source',{dataset:{label:'Play loop'}},{replace:${replace}})`,box)}
  vm.runInContext(`selected={phrase_id:${JSON.stringify(id)}}`,box);return vm.runInContext(`play({replace:${replace}})`,box);
 };
 const resolve=async(id,ok=true)=>{await new Promise(setImmediate);const url=atlas?id:`audio/${id}/loop.flac`;assert(pending.has(url));pending.get(url)({ok,arrayBuffer:async()=>id});await new Promise(setImmediate)};
 return {choose,resolve,sources,stop:()=>vm.runInContext('stop()',box),node,box};
}
for(const atlas of [false,true]){
 const label=atlas?'atlas':'main';
 for(const state of ['suspended','interrupted'])test(`${label}: Play resumes a browser paused loop in one click (${state})`,async()=>{
  const t=transport(atlas);const a=t.choose('a',false);await t.resolve('a');await a;
  vm.runInContext(`const audio=${atlas?'ctx':'context'};audio.state=${JSON.stringify(state)};audio.onstatechange()`,t.box);
  assert.match(t.node('status').textContent,/paused by the browser/);
  await t.choose('a',false);
  assert.equal(t.sources.length,2);assert.equal(t.sources[0].stopped,true);
  assert.equal(vm.runInContext(`${atlas?'ctx':'context'}.state`,t.box),'running');
  assert.match(t.node('status').textContent,/Looping/);
 });
 test(`${label}: keep old loop until replacement is ready and ignore stale selection`,async()=>{
  const t=transport(atlas);const a=t.choose('a',false);await t.resolve('a');await a;
  assert.equal(t.sources[0].loop,true);
  const b=t.choose('b');await new Promise(setImmediate);
  assert.equal(t.sources[0].stopped,undefined);
  const c=t.choose('c');await t.resolve('c');await c;
  assert.equal(t.sources[0].stopped,true);assert.equal(t.sources[1].buffer.id,'c');
  await t.resolve('b');await b;assert.equal(t.sources.length,2);
 });
 test(`${label}: Stop cancels a pending replacement`,async()=>{
  const t=transport(atlas);const a=t.choose('a',false);await t.resolve('a');await a;
  const b=t.choose('b');t.stop();await new Promise(setImmediate);
  // Stop can cancel before fetch or while it is in flight.
  assert.equal(t.sources[0].stopped,true);
  await b;assert.equal(t.sources.length,1);
 });
 test(`${label}: Stop cancels a replacement already fetching audio`,async()=>{
  const t=transport(atlas);const a=t.choose('a',false);await t.resolve('a');await a;
  const b=t.choose('b');await new Promise(setImmediate);t.stop();await t.resolve('b');await b;
  assert.equal(t.sources[0].stopped,true);assert.equal(t.sources.length,1);
 });
 test(`${label}: rapid selection during first load starts only the latest`,async()=>{
  const t=transport(atlas);const a=t.choose('a',false);await new Promise(setImmediate);
  const b=t.choose('b');await t.resolve('b');await b;await t.resolve('a');await a;
  assert.equal(t.sources.length,1);assert.equal(t.sources[0].buffer.id,'b');
 });
 test(`${label}: failed audio stops playback and reports an error`,async()=>{
  const t=transport(atlas);const a=t.choose('a',false);await t.resolve('a');await a;
  const b=t.choose('b');await t.resolve('b',false);await b;
  assert.equal(t.sources[0].stopped,true);assert.match(t.node('status').textContent,/could not load/);
 });
 test(`${label}: stop during an in-flight first load cannot restart audio`,async()=>{
  const t=transport(atlas);const a=t.choose('a',false);await new Promise(setImmediate);t.stop();await t.resolve('a');await a;assert.equal(t.sources.length,0);
 });
}
