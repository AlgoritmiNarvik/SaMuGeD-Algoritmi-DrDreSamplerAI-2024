/* A live note view. The existing audio player owns sound and the playback clock. */
(()=>{
 'use strict';
 function cyclePhase(seconds,duration){return Number.isFinite(seconds)&&Number.isFinite(duration)&&duration>0?((seconds%duration)+duration)%duration:0}
 function noteActive(note,phase){return note.start<=phase&&phase<note.end}
 if(typeof module!=='undefined')module.exports={cyclePhase,noteActive};
 if(typeof document==='undefined'||!catalog.explainer)return;
 const ns='http://www.w3.org/2000/svg',roll=document.getElementById('intro-notes'),drumRoll=document.getElementById('intro-drums');
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 let demo=null,stage='song',zoomGroup=null,head=null,drumHead=null,motion=null,noteNodes=[],drumNodes=[];
 const node=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n};
 const pitchName=p=>['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'][p%12]+(Math.floor(p/12)-1);
 const targetTransform=z=>z===1?'translate(0px,0px) scaleX(1)':`translate(${287.5-z*((demo.selected_start_tick+demo.period_ticks/2)/demo.context_ticks*575)}px,0px) scaleX(${z})`;
 function setStage(next){
  if(!demo)return;
  stage=next;
  document.querySelectorAll('[data-motion]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.motion===next)));
  document.getElementById('motion-caption').textContent={song:'A passage from Schism. The marked note patterns repeat.',phrase:'Keep one repeated phrase, with its original notes and rhythm.',loop:'One phrase, on repeat. Download MIDI to change its sound in your music app.'}[next];
  const nextZoom=next==='song'?1:next==='phrase'?2.2:demo.context_ticks/demo.period_ticks;
  const from=getComputedStyle(zoomGroup).transform,to=targetTransform(nextZoom);
  motion?.cancel();zoomGroup.style.transform=to;
  if(!reduced.matches)motion=zoomGroup.animate([{transform:from},{transform:to}],{duration:850,easing:'cubic-bezier(.22,1,.36,1)'});
  drumRoll.toggleAttribute('hidden',next!=='loop');
 }
 function build(){
  const pitches=demo.context_notes.map(n=>n.pitch),min=Math.min(...pitches),max=Math.max(...pitches);
  const y=p=>20+(max-p)/Math.max(1,max-min)*150;
  roll.replaceChildren();
  const defs=node('defs',{}),clip=node('clipPath',{id:'note-view-clip'});clip.append(node('rect',{x:0,y:0,width:575,height:185}));defs.append(clip);roll.append(defs);
  for(const p of [...new Set(pitches)].sort((a,b)=>b-a)){roll.append(node('text',{x:4,y:y(p)+4,class:'motion-label'},pitchName(p)));roll.append(node('line',{x1:48,x2:630,y1:y(p)+4,y2:y(p)+4,class:'motion-grid'}))}
  const outer=node('g',{transform:'translate(50,0)'}),clipped=node('g',{'clip-path':'url(#note-view-clip)'});
  zoomGroup=node('g',{});clipped.append(zoomGroup);outer.append(clipped);roll.append(outer);
  for(const r of demo.repeats)zoomGroup.append(node('rect',{x:r.start/demo.context_ticks*575,y:8,width:(r.end-r.start)/demo.context_ticks*575,height:173,class:'selection-window','vector-effect':'non-scaling-stroke'}));
  noteNodes=demo.context_notes.map(n=>{const r=node('rect',{x:n.start/demo.context_ticks*575,y:y(n.pitch),width:Math.max(.7,(n.end-n.start)/demo.context_ticks*575),height:7,class:'midi-note'});zoomGroup.append(r);return[n,r]});
  head=node('line',{x1:0,x2:0,y1:8,y2:181,class:'motion-playhead','vector-effect':'non-scaling-stroke'});zoomGroup.append(head);head.style.opacity='0';
  drumRoll.replaceChildren();
  for(const[label,i]of [['Kick',0],['Snare',1],['Other',2]]){drumRoll.append(node('text',{x:4,y:21+i*25,class:'motion-label'},label));drumRoll.append(node('line',{x1:50,x2:625,y1:18+i*25,y2:18+i*25,class:'motion-grid'}))}
  drumNodes=demo.drums.map(n=>{const lane=[35,36].includes(n.pitch)?0:[38,40].includes(n.pitch)?1:2;const c=node('circle',{cx:50+n.start/demo.cycle_seconds*575,cy:18+lane*25,r:2+n.velocity/127*2,class:'drum-hit'});drumRoll.append(c);return[n,c]});
  drumHead=node('line',{x1:50,x2:50,y1:4,y2:78,class:'motion-playhead'});drumRoll.append(drumHead);
  document.getElementById('intro-midi').href=`audio/${demo.paired_id}/loop.mid`;
  setStage(stage);
 }
 function frame(clock){
  if(!demo)return;
  const playing=clock?.running,phase=playing?cyclePhase(clock.seconds,clock.duration):0;
  const melodic=playing&&clock.layer!=='drums',drums=playing&&clock.layer!=='solo';
  for(const[n,r]of noteNodes)r.classList.toggle('active',!!(melodic&&noteActive({start:n.start_seconds,end:n.end_seconds},phase)));
  for(const[n,c]of drumNodes)c.classList.toggle('active',!!(drums&&phase>=n.start&&phase<n.start+.09));
  const x=(demo.selected_start_tick+phase/demo.cycle_seconds*demo.period_ticks)/demo.context_ticks*575;
  head.setAttribute('x1',x);head.setAttribute('x2',x);head.style.opacity=playing?'1':'0';
  drumHead.setAttribute('x1',50+phase/demo.cycle_seconds*575);drumHead.setAttribute('x2',50+phase/demo.cycle_seconds*575);drumHead.style.opacity=playing?'1':'0';
  const status=document.getElementById('intro-status'),text=playing?`Looping · ${clock.layer==='paired'?'bass + drums':clock.layer==='drums'?'drums only':'melody only'}`:'Press Play to hear the notes repeat.';
  if(status.textContent!==text)status.textContent=text;
 }
 window.loopExplainer={frame,setStage};
 document.querySelectorAll('[data-motion]').forEach(b=>b.addEventListener('click',()=>setStage(b.dataset.motion)));
 fetch('explainer.json').then(r=>{if(!r.ok)throw Error('Example unavailable');return r.json()}).then(data=>{demo=data;build()}).catch(()=>{document.getElementById('motion-caption').textContent='Explore the loops in the player below.'});
})();
