/* A view of MIDI events driven by the existing audio clock. No audio is scheduled here. */
(()=>{
 'use strict';
 const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
 const phase=(s,d)=>Number.isFinite(s)&&d>0?((s%d)+d)%d:0;
 const bounds=(duration,start,end,zoom,pan)=>{
  const width=Math.min(duration,Math.max(.05,(end-start)/zoom));
  const left=clamp(pan,0,duration-width);return [left,left+width];
 };
 // Interpolate span geometrically so a long song does not spend most of the transition zoomed out.
 function cameraAt(from,to,progress){
  if(progress<=0)return [...from];if(progress>=1)return [...to];
  const t=clamp(progress,0,1),e=t*t*(3-2*t);
  const width=Math.exp(Math.log(from[1]-from[0])*(1-e)+Math.log(to[1]-to[0])*e);
  const center=(from[0]+from[1])/2*(1-e)+(to[0]+to[1])/2*e;
  return [center-width/2,center+width/2,from[2]*(1-e)+to[2]*e,from[3]*(1-e)+to[3]*e];
 }
 function noteEnergy(start,end,time,duration,drum=false){
  if(duration<=0||start>=duration||end<=0)return 0;
  const release=Math.min(drum?.23:.3,duration/5);
  // Only carry the tail of a note near the boundary into the next audio cycle.
  const age=phase(time-start,duration),length=drum?Math.min(.055,Math.max(.02,end-start)):Math.max(.01,end-start);
  if(age<length)return drum?1: .78+.22*Math.exp(-age/ .065);
  return age<length+release?.65*Math.pow(1-(age-length)/release,2):0;
 }
 function drumLane(p){
  if([35,36].includes(p))return 'Kick';if([37,38,39,40].includes(p))return 'Snare';
  if([42,44].includes(p))return 'Closed hat';if(p===46)return 'Open hat';
  if([41,43,45,47,48,50].includes(p))return 'Toms';
  if([51,53,59].includes(p))return 'Ride';if([49,52,55,57].includes(p))return 'Crash';return 'Percussion';
 }
 const drumOrder=['Kick','Snare','Closed hat','Open hat','Toms','Ride','Crash','Percussion'];
 const drumColors={Kick:'#b8a5e4',Snare:'#d5af99','Closed hat':'#91b5ba','Open hat':'#91b5ba',Toms:'#b39abf',Ride:'#c7b98c',Crash:'#c7b98c',Percussion:'#a9a5b2'};
 // Symbolic MIDI envelopes, not isolated audio waveforms or measured sample decay.
 function drumEnvelope(start,y,p,velocity,compact=false){
  const length=({'Closed hat':.13,'Open hat':.34,Ride:.48,Crash:.62,Kick:.28,Snare:.24,Toms:.32})[drumLane(p)]||.2;
  const height=(compact?2.5:5)+(compact?2:6)*clamp(velocity,0,127)/127;
  const a=start+.008,b=start+length*.24,c=start+length;
  return `M${start} ${y}L${a} ${y-height}C${b} ${y-height*.2} ${b} ${y-height*.08} ${c} ${y}C${b} ${y+height*.08} ${b} ${y+height*.2} ${a} ${y+height}Z`;
 }
 if(typeof module!=='undefined')module.exports={phase,bounds,cameraAt,noteEnergy,drumLane};
 if(typeof document==='undefined')return;
 const cache=new Map();
 function createNoteExplorer({canvasId='player-notes',prefix='note-',captionId='note-caption',initialMode='phrase',viewAttribute='data-note-view',notesBase='notes',getLayer=()=>layer,relatedScope='main',onNavigate=id=>window.selectNotePhrase?.(id)}={}){
 const svg=document.getElementById(canvasId);if(!svg)return null;
 const ns='http://www.w3.org/2000/svg',reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const get=id=>document.getElementById(id==='note-caption'?captionId:id.replace(/^note-/,prefix));
 const clipId=canvasId+'-clip',beamId=canvasId+'-beam',glowId=canvasId+'-glow';
 const el=(tag,attrs={},text)=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n};
 const pitch=p=>['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'][p%12]+(Math.floor(p/12)-1);
 const load=path=>{if(!cache.has(path))cache.set(path,fetch(path).then(r=>{if(!r.ok)throw Error('Notes unavailable');return r.json()}).catch(e=>{cache.delete(path);throw e}));return cache.get(path)};
 const X=65,W=521,Y=20,H=114;
 let selection=null,song=null,row=null,token=0,sourceReady=false,mode=initialMode,camera=[0,1,48,60],motion=null;
 let scenes=[],axis=null,stage=null,cursor=null,sweep=null,windowBox=null,overviewWindow=null,overviewSelection=null,halos=[];
 let related=[],markerGroup=null,density=null,readout=null,timeReadout=null,rangeReadout=null,lastFrame=0,needsPaint=true,visible=true,wasRunning=false;
 // The offscreen player still follows the shared clock when it re-enters the viewport.
 const observer=typeof IntersectionObserver!=='undefined'?new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)needsPaint=true},{rootMargin:'100px'}):null;observer?.observe(svg);
 const navigation=document.createElement('div');navigation.className='note-navigation';navigation.hidden=true;
 const previous=document.createElement('button'),next=document.createElement('button'),select=document.createElement('select');
 previous.type=next.type='button';previous.textContent='←';next.textContent='→';previous.setAttribute('aria-label','Previous phrase in this song');next.setAttribute('aria-label','Next phrase in this song');select.setAttribute('aria-label','Prepared phrases in this song');
 navigation.append(previous,select,next);svg.after(navigation);
 const navigate=pid=>{if(pid!==row?.phrase_id&&related.some(r=>r.phrase_id===pid))onNavigate(pid)};
 previous.onclick=()=>navigate(related[related.findIndex(r=>r.phrase_id===row.phrase_id)-1]?.phrase_id);
 next.onclick=()=>navigate(related[related.findIndex(r=>r.phrase_id===row.phrase_id)+1]?.phrase_id);select.onchange=()=>navigate(select.value);
 function showRelated(){
  navigation.hidden=related.length<2;select.replaceChildren();markerGroup?.replaceChildren();
  const current=related.findIndex(r=>r.phrase_id===row.phrase_id);
  previous.disabled=current<=0;next.disabled=current>=related.length-1;
  related.forEach((item,i)=>{
   const label=`${i+1} / ${related.length} · ${item.label} · ${item.start.toFixed(1)} s`,option=document.createElement('option');option.value=item.phrase_id;option.textContent=label;select.append(option);
   if(!markerGroup||related.length<2)return;
   const marker=el('g',{role:'button',tabindex:0,'aria-label':`Play phrase ${label}`,class:'note-phrase-marker'}),xx=X+item.start/song.duration*W;
   marker.append(el('rect',{x:xx-5,y:234,width:Math.max(10,(item.end-item.start)/song.duration*W),height:24,fill:'transparent'}),el('line',{x1:xx,x2:xx,y1:236,y2:255,class:item.phrase_id===row.phrase_id?'current':''}));
   marker.addEventListener('click',()=>navigate(item.phrase_id));marker.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();navigate(item.phrase_id)}});markerGroup.append(marker);
  });select.value=row?.phrase_id||'';
 }
 const currentCamera=now=>motion?cameraAt(motion.from,motion.to,(now-motion.start)/motion.duration):camera;
 function setup(){
  svg.replaceChildren();scenes=[];
  const defs=el('defs'),clip=el('clipPath',{id:clipId});
  clip.append(el('rect',{x:X,y:8,width:W,height:202}));defs.append(clip);
  const beam=el('linearGradient',{id:beamId,x1:'0%',x2:'100%'});
  beam.append(el('stop',{offset:'0%','stop-color':'#cfc3ff','stop-opacity':0}),el('stop',{offset:'100%','stop-color':'#cfc3ff','stop-opacity':.12}));defs.append(beam);
  const glow=el('filter',{id:glowId,x:'-30%',y:'-150%',width:'160%',height:'400%'});glow.append(el('feGaussianBlur',{stdDeviation:2.5}));defs.append(glow);
  svg.append(defs,el('rect',{x:0,y:0,width:600,height:264,class:'note-field'}));
  axis=el('g');svg.append(axis);
  const clipped=el('g',{'clip-path':`url(#${clipId})`});svg.append(clipped);
  windowBox=el('rect',{y:9,height:198,class:'note-selection'});clipped.append(windowBox);
  const resonance=el('g',{filter:`url(#${glowId})`,'aria-hidden':'true'});halos=Array.from({length:20},()=>{const r=el('rect',{height:9,opacity:0});resonance.append(r);return r});clipped.append(resonance);
  stage=el('g');clipped.append(stage);
  sweep=el('rect',{y:10,width:30,height:194,fill:`url(#${beamId})`});clipped.append(sweep);
  cursor=el('g',{class:'note-cursor'});cursor.append(el('line',{x1:0,x2:0,y1:13,y2:202}),el('path',{d:'M-3 7H3L0 11Z'}));clipped.append(cursor);
  const overview=el('g',{class:'note-overview'});
  overview.append(el('rect',{x:X,y:237,width:W,height:18,class:'overview-track'}));
  // A density ribbon gives scale without drawing thousands of tiny full-song notes again.
  density=el('g');overview.append(density);drawDensity();
  overviewSelection=el('rect',{x:X+selection.start/song.duration*W,y:236,width:Math.max(2,(selection.end-selection.start)/song.duration*W),height:20,class:'overview-selection'});overview.append(overviewSelection);
  overviewWindow=el('rect',{y:235,height:22,class:'overview-window'});overview.append(overviewWindow);svg.append(overview);markerGroup=el('g');svg.append(markerGroup);showRelated();
  svg.append(el('text',{x:7,y:249,class:'note-axis-label'},'Song'));
  readout=el('text',{x:X,y:226,class:'note-readout'},'');timeReadout=el('text',{x:586,y:226,'text-anchor':'end',class:'note-time'},'');svg.append(readout,timeReadout);
  rangeReadout=get('note-range');
 }
 function drawDensity(){
  if(!density)return;density.replaceChildren();const bins=Array(128).fill(0);
  for(const n of song.notes)if(n[4]||n[5]===selection.part)bins[Math.min(127,Math.floor(n[0]/song.duration*128))]++;
  const max=Math.max(1,...bins);
  bins.forEach((v,i)=>{if(v)density.append(el('rect',{x:X+i*W/128,y:252-v/max*12,width:2,height:Math.max(1,v/max*12),class:'overview-density'}))});
 }
 function sceneNotes(){
  if(mode==='song')return song.notes.filter(n=>get('note-all').checked||n[4]||n[5]===selection.part);
  return (selection.variants[getLayer()]||selection.variants.solo).map(n=>[n[0]+selection.start,n[1]+selection.start,...n.slice(2)]);
 }
 function makeScene(){
 const g=el('g',{class:'note-scene'}),melody=el('g'),drums=el('g'),envelopes=el('g',{class:'note-envelopes'});drums.append(envelopes);g.append(melody,drums);stage.append(g);
  const onlyDrums=row.kind==='percussion'||getLayer()==='drums';
  const notes=sceneNotes().filter(n=>!onlyDrums||n[4]),entries=[];
  const laneKey=p=>onlyDrums?drumLane(p):[35,36].includes(p)?'Kick':[37,38,39,40].includes(p)?'Snare':[42,44,46].includes(p)?'Hats':'Other';
  const keys=new Set(notes.filter(n=>n[4]).map(n=>laneKey(n[2])));
  const lanes=(onlyDrums?drumOrder:['Kick','Snare','Hats','Other']).filter(k=>keys.has(k));
  const drumY=p=>{const i=lanes.indexOf(laneKey(p));return onlyDrums?25+i*170/Math.max(1,lanes.length-1):151+i*48/Math.max(1,lanes.length-1)};
  for(const n of notes){
   const drum=!!n[4];
   const r=drum?el('line',{x1:n[0],x2:n[0],y1:drumY(n[2])-(onlyDrums?5:2.5),y2:drumY(n[2])+(onlyDrums?5:2.5),class:'note-event note-drum','vector-effect':'non-scaling-stroke'}):el('rect',{x:n[0],y:-n[2]-.34,width:Math.max(.009,n[1]-n[0]),height:.68,class:'note-event note-melody','vector-effect':'non-scaling-stroke'});
   let envelope=null;
   if(drum){r.style.setProperty('--hit-color',drumColors[drumLane(n[2])]);r.style.setProperty('--hit-width',(onlyDrums?1.5:1)+n[3]/127*(onlyDrums?3:1.5));
    if(mode==='phrase'){envelope=el('path',{d:drumEnvelope(n[0],drumY(n[2]),n[2],n[3],!onlyDrums),class:'note-hit-envelope',fill:drumColors[drumLane(n[2])],opacity:.28});envelopes.append(envelope)}
   }
   r.append(el('title',{},`${drum?'Drum '+n[2]:pitch(n[2])} · ${(n[0]-(mode==='phrase'?selection.start:0)).toFixed(2)}s · velocity ${n[3]}`));
   (drum?drums:melody).append(r);entries.push({n,r,envelope,energy:-1,base:.3+.42*n[3]/127});
  }
  return {g,melody,drums,entries,mode,layer:getLayer(),onlyDrums,lanes,drumY,opacity:1};
 }
 function pitchRange(notes){
  const melodic=notes.filter(n=>!n[4]);if(!melodic.length)return [48,60];
  let lo=127,hi=0;for(const n of melodic){lo=Math.min(lo,n[2]);hi=Math.max(hi,n[2])}
  const padding=Math.max(1,(8-(hi-lo))/2);return [lo-padding,hi+padding];
 }
 function drawAxis(){
  axis.replaceChildren();
  const [left,right,low,high]=camera,width=right-left,x=t=>X+(t-left)/width*W,y=p=>Y+(high-p)/(high-low)*H;
  let pitches=[];for(let p=Math.ceil(low);p<=high;p++)if(p%12===0||high-low<20&&p%12===7)pitches.push(p);
  if(pitches.length<2)pitches=[Math.ceil(low+1),Math.floor(high-1)];
  if(!scenes.at(-1)?.onlyDrums)for(const p of pitches){axis.append(el('line',{x1:X,x2:X+W,y1:y(p),y2:y(p),class:'note-grid'}),el('text',{x:7,y:y(p)+3,class:'note-axis-label'},pitch(p)))}
  const scene=scenes.at(-1);
  if(scene)scene.lanes.forEach((label,i)=>{const yy=scene.onlyDrums?25+i*170/Math.max(1,scene.lanes.length-1):151+i*48/Math.max(1,scene.lanes.length-1);axis.append(el('line',{x1:X,x2:X+W,y1:yy,y2:yy,class:'note-drum-grid'}),el('text',{x:5,y:yy+3,class:'note-axis-label'},label==='Closed hat'?'C. hat':label==='Open hat'?'O. hat':label==='Percussion'?'Perc.':label))});
  if(mode==='phrase'&&selection.beat_grid){
   for(const [seconds,beat]of selection.beat_grid){const xx=x(selection.start+seconds);if(xx<X||xx>X+W)continue;axis.append(el('line',{x1:xx,x2:xx,y1:12,y2:201,class:Number.isInteger(beat)?'note-beat-grid':'note-time-grid'}));if(Number.isInteger(beat)&&seconds<row.cycle_seconds-.001)axis.append(el('text',{x:xx,y:213,class:'note-axis-label'},String(beat+1)))}
   return;
  }
  const unit=10**Math.floor(Math.log10(width/5)),step=unit*([1,2,5,10].find(v=>v*unit>=width/5)||10);
  const origin=mode==='phrase'?selection.start:0;
  for(let relative=Math.ceil((left-origin)/step)*step;relative+origin<right;relative+=step){const xx=x(relative+origin);axis.append(el('line',{x1:xx,x2:xx,y1:12,y2:201,class:'note-time-grid'}))}
 }
 function paintGeometry(){
  const [left,right,low,high]=camera,sx=W/(right-left),sy=H/(high-low),tx=X-left*sx,ty=Y+high*sy;
  for(const scene of scenes){scene.melody.setAttribute('transform',`matrix(${sx} 0 0 ${sy} ${tx} ${ty})`);scene.drums.setAttribute('transform',`matrix(${sx} 0 0 1 ${tx} 0)`)}
  windowBox.setAttribute('x',X+(selection.start-left)*sx);windowBox.setAttribute('width',(selection.end-selection.start)*sx);windowBox.style.opacity=mode==='song'?1:0;
  const a=clamp(left,0,song.duration),b=clamp(right,0,song.duration);
  overviewWindow.setAttribute('x',X+a/song.duration*W);overviewWindow.setAttribute('width',Math.max(2,(b-a)/song.duration*W));
  drawAxis();
 }
 function moveTo(target,animate=true){
  const now=performance.now(),from=currentCamera(now);camera=from;
  motion=animate&&!reduced.matches?{from,to:target,start:now,duration:620}:null;
  if(!motion)camera=target;
  needsPaint=true;
 }
 function draw({reset=false,rebuild=false,animate=true}={}){
  if(!selection||!song)return;
  const duration=mode==='song'?song.duration:row.cycle_seconds,offset=mode==='song'?0:selection.start;
  const zoom=get('note-zoom'),pan=get('note-pan');if(reset){zoom.value='1';pan.value='0'}
  const range=bounds(duration,0,duration,Number(zoom.value),Number(pan.value));pan.max=Math.max(0,duration-(range[1]-range[0]));pan.value=range[0];pan.disabled=Number(pan.max)===0;
  if(rebuild||!scenes.length){
   // Keep one outgoing scene for the crossfade. Fast repeated clicks cannot accumulate layers.
   while(scenes.length>1)scenes.shift().g.remove();
   const scene=makeScene();scenes.push(scene);
   scenes.forEach((s,i)=>{s.opacity=i===scenes.length-1?0:1});
  }
  const visibleNotes=scenes.at(-1).entries.map(e=>e.n).filter(n=>n[0]<range[1]+offset&&n[1]>range[0]+offset);
  const [lo,hi]=pitchRange(visibleNotes);
  moveTo([range[0]+offset,range[1]+offset,lo,hi],animate);
  if(rangeReadout)rangeReadout.textContent=`${range[0].toFixed(1)}–${range[1].toFixed(1)} s`;
  document.querySelectorAll(`[${viewAttribute}]`).forEach(b=>b.setAttribute('aria-pressed',String(b.getAttribute(viewAttribute)===mode)));
  get('note-all-label').hidden=mode!=='song'||scenes.at(-1).onlyDrums;
  get('note-caption').textContent=mode==='song'?(sourceReady?'The highlighted passage becomes your loop. Zoom in to follow its notes.':'Loading the full song map…'):(scenes.at(-1).onlyDrums?'Each lane is a kit voice. Hit size shows MIDI velocity. Tails illustrate decay, not isolated audio.':'Notes light up as they sound. Lower lanes show MIDI drum attacks with symbolic decay tails.');
 }
 async function choose(next){
  const id=++token;selection=null;row=next;motion=null;related=[];navigation.hidden=true;
  svg.style.opacity='.3';get('note-caption').textContent='Loading source notes…';
  try{
   const data=await load(`${notesBase}/${next.phrase_id}.json`);if(id!==token)return;
   selection=data;sourceReady=false;
   song={duration:data.source_duration||data.end,notes:(data.variants.paired||data.variants.solo).map(n=>[n[0]+data.start,n[1]+data.start,...n.slice(2)])};
   setup();draw({reset:true,rebuild:true,animate:false});svg.style.opacity='1';
   load(`${notesBase}/index.json`).then(index=>{if(id!==token)return;related=(index[data.song]||[]).filter(r=>r.scopes.includes(relatedScope));showRelated()}).catch(()=>{});
   // The playable phrase is ready before the larger source map. Stale responses cannot replace it.
   load(`${notesBase}/${data.song}.json`).then(source=>{if(id!==token)return;song=source;sourceReady=true;drawDensity();
    if(mode==='song'){setup();draw({rebuild:true,animate:false})}
   }).catch(()=>{if(id===token&&mode==='song')get('note-caption').textContent='Source map could not load. The phrase and audio are available.'});
   if(!reduced.matches)stage.animate([{opacity:0,transform:'translateY(3px)'},{opacity:1,transform:'translateY(0)'}],{duration:360,easing:'cubic-bezier(.2,.7,.2,1)'});
  }catch{if(id===token){svg.replaceChildren();svg.style.opacity='1';get('note-caption').textContent='Note view unavailable. Audio playback is unchanged.'}}
 }
 function frame(clock){
  if(!selection||!scenes.length||!visible)return;
  const now=performance.now();if(now-lastFrame<15&&!needsPaint&&!motion)return;lastFrame=now;
  const running=clock?.running&&clock.id===row.phrase_id;
  if(!running&&!wasRunning&&!needsPaint&&!motion)return;wasRunning=!!running;
  if(motion){camera=currentCamera(now);if(now-motion.start>=motion.duration){camera=motion.to;motion=null}needsPaint=true}
  if(needsPaint){paintGeometry();needsPaint=false}
  const blend=motion&&scenes.length>1?clamp((now-motion.start)/260,0,1):1;
  scenes.forEach((s,i)=>{s.g.style.opacity=i===scenes.length-1?blend:1-blend});
  if(!motion&&scenes.length>1)scenes.shift().g.remove();
  const p=running?phase(clock.seconds,clock.duration):0,t=selection.start+p;
  const names=new Set();let haloIndex=0;
  for(const scene of scenes)for(const entry of scene.entries){
   const {n,r,base}=entry;
   // Other instruments remain context only. Their notes are not present in the selected audio.
   const audible=running&&(clock.layer!=='drums'||n[4])&&(clock.layer!=='solo'||row.kind==='percussion'||!n[4])&&(scene.mode!=='song'||n[4]||n[5]===selection.part);
   const start=n[0]-selection.start,end=n[1]-selection.start;
   const energy=audible&&start>=-.001&&start<clock.duration?noteEnergy(start,end,p,clock.duration,!!n[4]):0;
   const level=reduced.matches?(energy>.66?1:0):Math.round(energy*16)/16;
   if(level!==entry.energy){entry.energy=level;r.setAttribute('opacity',base+(1-base)*level);r.classList.toggle('is-sounding',level>.65);r.classList.toggle('is-releasing',level>0&&level<=.65);r.style.setProperty('--note-energy',level);entry.envelope?.setAttribute('opacity',.2+base*.14+level*.42)}
   if(energy>.65&&scene===scenes.at(-1))names.add(n[4]?(scene.onlyDrums?drumLane(n[2]):''):pitch(n[2]));names.delete('');
   if(energy>0&&!reduced.matches&&scene===scenes.at(-1)&&haloIndex<halos.length&&n[0]<camera[1]&&n[1]>camera[0]){
    const left=clamp(X+(n[0]-camera[0])/(camera[1]-camera[0])*W,X,X+W);
    const right=clamp(X+((n[4]?Math.min(n[1],n[0]+.065):n[1])-camera[0])/(camera[1]-camera[0])*W,X,X+W);
    const y=n[4]?scene.drumY(n[2]):Y+(camera[3]-n[2])/(camera[3]-camera[2])*H;
    const halo=halos[haloIndex++];halo.setAttribute('x',left-2);halo.setAttribute('y',y-4);halo.setAttribute('width',Math.max(3,right-left+4));halo.setAttribute('fill',n[4]?'#dca789':'#c8b5ff');halo.setAttribute('opacity',energy*.22);
   }
  }
  for(let i=haloIndex;i<halos.length;i++)halos[i].setAttribute('opacity',0);
  const x=X+(t-camera[0])/(camera[1]-camera[0])*W,show=running&&x>=X&&x<=X+W;
  cursor.setAttribute('transform',`translate(${x} 0)`);cursor.style.opacity=show?'1':'0';
  sweep.setAttribute('x',x-30);sweep.style.opacity=show&&!reduced.matches?'1':'0';
  const label=running?(names.size?[...names].slice(0,4).join(' · '):'Rhythm'):'Notes + rhythm';if(readout.textContent!==label)readout.textContent=label;
  const timing=running?`${p.toFixed(1)} / ${clock.duration.toFixed(1)} s`:`${row.cycle_seconds.toFixed(1)} s loop`;if(timeReadout.textContent!==timing)timeReadout.textContent=timing;
  svg.classList.toggle('is-playing',!!running);
 }
 document.querySelectorAll(`[${viewAttribute}]`).forEach(b=>b.onclick=()=>{mode=b.getAttribute(viewAttribute);draw({reset:true,rebuild:true})});
 get('note-zoom').oninput=()=>draw({animate:false});get('note-pan').oninput=()=>draw({animate:false});get('note-all').onchange=()=>draw({rebuild:true});
 if(get('note-fit'))get('note-fit').onclick=()=>draw({reset:true});
 function focus(){
  if(!selection)return;const rebuild=mode!=='song';mode='song';
  get('note-zoom').value=Math.min(128,song.duration/Math.max(.05,selection.end-selection.start));
  get('note-pan').max=song.duration;get('note-pan').value=selection.start;draw({rebuild});
 }
 if(get('note-focus'))get('note-focus').onclick=focus;
 const motionPreference=()=>{if(motion){camera=motion.to;motion=null;needsPaint=true}};reduced.addEventListener('change',motionPreference);
 return {choose,destroy(){token++;navigation.remove();observer?.disconnect();reduced.removeEventListener('change',motionPreference)},prefetch:ids=>{for(const id of ids)load(`${notesBase}/${id}.json`).catch(()=>{})},refresh:()=>draw({rebuild:true}),frame,setStage(stage){if(stage==='phrase'){focus();return}mode=stage==='song'?'song':'phrase';draw({reset:true,rebuild:true})}};
 }
 window.createNoteExplorer=createNoteExplorer;
 if(document.getElementById('player-notes')){window.playerNotes=createNoteExplorer();if(typeof selected!=='undefined'&&selected)window.playerNotes.choose(selected)}
})();
