/* The opening Schism example shares the player's note renderer and audio clock. */
(()=>{
 'use strict';
 function cyclePhase(seconds,duration){return Number.isFinite(seconds)&&Number.isFinite(duration)&&duration>0?((seconds%duration)+duration)%duration:0}
 function noteActive(note,phase){return note.start<=phase&&phase<note.end}
 if(typeof module!=='undefined')module.exports={cyclePhase,noteActive};
 if(typeof document==='undefined'||!catalog.explainer||!window.createNoteExplorer)return;
 const row=catalog.groups.popular.rows.find(r=>r.phrase_id===catalog.explainer.phrase_id);if(!row)return;
 let introLayer='paired';
 const view=window.createNoteExplorer({canvasId:'intro-notes',prefix:'intro-note-',captionId:'motion-caption',initialMode:'song',viewAttribute:'data-intro-note-view',getLayer:()=>introLayer,relatedScope:'intro'});
 let stage='song';
 function setStage(next){
  stage=next;view.setStage(next);
  document.querySelectorAll('[data-motion]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.motion===next)));
  document.getElementById('motion-caption').textContent={song:'A phrase inside Schism. Follow the highlighted passage.',phrase:'Zoom into the source notes and the drum rhythm around them.',loop:'One phrase, on repeat. Take the MIDI into your music app.'}[next];
 }
 function frame(clock){
  if(clock&&clock.layer!==introLayer){introLayer=clock.layer;view.refresh()}
  view.frame(clock?{...clock,id:row.phrase_id}:null);
  const status=document.getElementById('intro-status'),text=clock?.running?`Looping · ${clock.layer==='paired'?'bass + drums':clock.layer==='drums'?'drums only':'melody only'}`:'Press Play to hear the notes repeat.';
  if(status.textContent!==text)status.textContent=text;
 }
 document.getElementById('intro-midi').href=`audio/${row.with_drums?.phrase_id||row.phrase_id}/loop.mid`;
 document.querySelectorAll('[data-motion]').forEach(b=>b.addEventListener('click',()=>setStage(b.dataset.motion)));
 window.loopExplainer={frame,setStage};view.choose(row).then(()=>setStage(stage));
})();
