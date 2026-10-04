/* Analytics uses the same source-cycle view as the listening collection. */
(()=>{
 'use strict';
 window.mountAtlasNotes=(row,audio)=>{
  window.atlasNotes?.destroy();window.atlasNotes=null;if(!audio)return;
  const box=document.getElementById('detail'),template=document.getElementById('atlas-note-template');
  const visual=template.content.cloneNode(true),controls=box.querySelector('.controls');if(controls)controls.after(visual);else box.append(visual);
  window.atlasNoteLayer=audio.with_drums?'paired':'solo';
  window.atlasNotes=window.createNoteExplorer({canvasId:'atlas-notes',prefix:'atlas-note-',captionId:'atlas-note-caption',viewAttribute:'data-atlas-note-view',notesBase:'../notes',getLayer:()=>window.atlasNoteLayer,relatedScope:'atlas',onNavigate:id=>{const entry=Object.entries(data.views).find(([key,rows])=>key===view&&rows.some(r=>r.phrase_id===id))||Object.entries(data.views).find(([,rows])=>rows.some(r=>r.phrase_id===id));if(entry){view=entry[0];document.getElementById('search').value='';render(id)}}});
  window.atlasNotes.choose({...row,cycle_seconds:audio.cycle_seconds});
 };
 function frame(){
  window.atlasNotes?.frame(typeof playing!=='undefined'&&playing&&wantsPlayback&&ctx?{id:playingPhrase,seconds:ctx.currentTime-started,duration:playing.buffer.duration,running:ctx.state==='running',layer:playingLayer}:null);
  requestAnimationFrame(frame);
 }
 requestAnimationFrame(frame);
})();
