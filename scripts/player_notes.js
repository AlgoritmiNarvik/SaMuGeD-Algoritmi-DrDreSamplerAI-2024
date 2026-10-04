/* Note visualization follows the audio transport. It never starts or changes sound. */
(()=>{
 'use strict';
 const phase=(s,d)=>Number.isFinite(s)&&d>0?((s%d)+d)%d:0;
 const bounds=(duration,start,end,zoom,pan)=>{const width=Math.min(duration,Math.max(.05,(end-start)/zoom));const left=Math.max(0,Math.min(duration-width,pan));return [left,left+width]};
 if(typeof module!=='undefined')module.exports={phase,bounds};
 if(typeof document==='undefined')return;
 const svg=document.getElementById('player-notes');if(!svg)return;
 const ns='http://www.w3.org/2000/svg',cache=new Map();let selection=null,song=null,row=null,token=0,mode='phrase',range=[0,1],nodes=[],head=null;
 const el=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n};
 const pitch=p=>['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'][p%12]+(Math.floor(p/12)-1);
 const get=path=>{if(!cache.has(path))cache.set(path,fetch(path).then(r=>{if(!r.ok)throw Error('Notes unavailable');return r.json()}).catch(e=>{cache.delete(path);throw e}));return cache.get(path)};
 function draw(reset=false){
  if(!selection||!song)return;
  const songMode=mode==='song',duration=songMode?song.duration:row.cycle_seconds;
  const zoom=document.getElementById('note-zoom'),pan=document.getElementById('note-pan');
  if(reset){zoom.value='1';pan.value='0'}
  range=bounds(duration,0,duration,Number(zoom.value),Number(pan.value));pan.max=Math.max(0,duration-(range[1]-range[0]));pan.value=range[0];pan.disabled=Number(pan.max)===0;
  document.querySelectorAll('[data-note-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.noteView===mode)));
  const all=document.getElementById('note-all').checked;
  let notes=songMode?song.notes.filter(n=>all||n[4]||n[5]===selection.part):selection.variants[layer]||selection.variants.solo;
  notes=notes.filter(n=>n[0]<range[1]&&n[1]>range[0]);
  const melodic=notes.filter(n=>!n[4]),low=melodic.length?Math.min(...melodic.map(n=>n[2]))-1:48,high=melodic.length?Math.max(...melodic.map(n=>n[2]))+1:60;
  const x=t=>50+(t-range[0])/(range[1]-range[0])*540,y=p=>20+(high-p)/Math.max(1,high-low)*115;
  svg.replaceChildren();nodes=[];
  svg.append(el('rect',{x:50,y:0,width:540,height:196,fill:'#101012'}));
  for(let p=low;p<=high;p++){if(p%12===0||high-low<18&&p%12===7){svg.append(el('line',{x1:50,x2:590,y1:y(p)+3,y2:y(p)+3,class:'motion-grid'}));svg.append(el('text',{x:3,y:y(p)+6,class:'motion-label'},pitch(p)))}}
  const step=Math.pow(10,Math.floor(Math.log10((range[1]-range[0])/5)));const interval=step*([1,2,5,10].find(v=>v*step>=(range[1]-range[0])/6)||10);
  for(let t=Math.ceil(range[0]/interval)*interval;t<range[1];t+=interval){svg.append(el('line',{x1:x(t),x2:x(t),y1:8,y2:184,class:'motion-grid'}));svg.append(el('text',{x:x(t),y:210,class:'motion-label'},`${Number(t.toFixed(1))}s`))}
  if(songMode){const a=Math.max(range[0],selection.start),b=Math.min(range[1],selection.end);if(b>a)svg.append(el('rect',{x:x(a),y:6,width:x(b)-x(a),height:181,class:'selection-window'}))}
  svg.append(el('text',{x:3,y:168,class:'motion-label'},'Drums'));
  const scene=el('g',{class:reset?'note-scene':''});svg.append(scene);
  for(const n of notes){const a=Math.max(range[0],n[0]),b=Math.min(range[1],n[1]);const drum=n[4],lane=[35,36].includes(n[2])?0:[38,40].includes(n[2])?1:2;const r=el('rect',{x:x(a),y:drum?151+lane*10:y(n[2]),width:Math.max(1.2,x(b)-x(a)),height:drum?5:5,class:drum?'drum-hit':'midi-note'});r.append(el('title',{},`${drum?'Drum '+n[2]:pitch(n[2])} · ${n[0].toFixed(2)}s · velocity ${n[3]}`));scene.append(r);nodes.push([n,r])}
  head=el('line',{x1:50,x2:50,y1:6,y2:184,class:'motion-playhead'});head.style.opacity='0';svg.append(head);
  document.getElementById('note-caption').textContent=songMode?'Source MIDI. The marked passage is the selected loop.':'One audio cycle. Note length shows duration, drum lanes show attacks.';
  document.getElementById('note-all-label').hidden=!songMode;
 }
 async function choose(next){row=next;selection=null;song=null;const id=++token;svg.replaceChildren();document.getElementById('note-caption').textContent='Loading source notes…';try{const data=await get(`notes/${next.phrase_id}.json`);const source=await get(`notes/${data.song}.json`);if(id!==token)return;selection=data;song=source;draw(true)}catch{if(id===token)document.getElementById('note-caption').textContent='Note view unavailable. Audio playback is unchanged.'}}
 function frame(clock){if(!selection||!head)return;const running=clock?.running&&clock.id===row.phrase_id,p=running?phase(clock.seconds,clock.duration):0,t=mode==='song'?selection.start+p:p;for(const[n,r]of nodes)r.classList.toggle('active',!!(running&&n[0]<=t&&t<n[1]&&(clock.layer!=='drums'||n[4])&&(clock.layer!=='solo'||row.kind==='percussion'||!n[4])&&(mode!=='song'||n[4]||n[5]===selection.part)));const x=50+(t-range[0])/(range[1]-range[0])*540;head.setAttribute('x1',x);head.setAttribute('x2',x);head.style.opacity=running&&x>=50&&x<=590?'1':'0'}
 document.querySelectorAll('[data-note-view]').forEach(b=>b.onclick=()=>{mode=b.dataset.noteView;draw(true)});
 document.getElementById('note-zoom').oninput=()=>draw();document.getElementById('note-pan').oninput=()=>draw();document.getElementById('note-all').onchange=()=>draw();
 document.getElementById('note-fit').onclick=()=>draw(true);
 document.getElementById('note-focus').onclick=()=>{if(!selection)return;mode='song';document.getElementById('note-zoom').value=Math.min(128,song.duration/Math.max(.05,selection.end-selection.start));document.getElementById('note-pan').max=song.duration;document.getElementById('note-pan').value=selection.start;draw()};
 window.playerNotes={choose,refresh:()=>draw(),frame};if(selected)choose(selected);
})();
