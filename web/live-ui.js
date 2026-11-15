const $=id=>document.getElementById(id);
let TOKEN=document.querySelector('meta[name=app-token]').content;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clock=s=>{s=Math.max(0,Math.floor(s||0));return `${Math.floor(s/3600)}:${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`};
let library,session,player,context,poller,previewAudio,sessionEpoch=0;
function log(message){$('events').textContent=`${new Date().toLocaleTimeString()} ${message}\n`+$('events').textContent.split('\n').slice(0,70).join('\n')}
async function api(path,options={}){
  for(let attempt=0;attempt<2;attempt++){
    const r=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers,'X-App-Token':TOKEN}});
    const data=await r.json();
    if(r.status===403&&data.error==='Reload the app page before submitting'&&attempt===0){
      const page=await fetch('/',{cache:'no-store'});if(!page.ok)throw Error('Cannot reconnect to the local server');
      const token=new DOMParser().parseFromString(await page.text(),'text/html').querySelector('meta[name=app-token]')?.content;
      if(!token)throw Error('Reload the app page before submitting');TOKEN=token;
      document.querySelector('meta[name=app-token]').content=token;log('Reconnected after server restart, retrying request');continue;
    }
    if(!r.ok)throw Error(data.error||'Request failed');return data;
  }
}
function fail(e){$('error').textContent=String(e);log(String(e))}
function initPlayer(){
  if(player)return player;
  context=new (window.AudioContext||window.webkitAudioContext)({latencyHint:'playback'});
  player=new LivePodcast.PodcastPlayer(library.episode,{context,loadBuffer:async url=>{const r=await fetch(url);if(!r.ok)throw Error('Audio unavailable: '+r.status);return context.decodeAudioData(await r.arrayBuffer())},onEvent:e=>{
    if(e.type==='scheduled')return;
    if(e.type==='ad_skipped')log(`Skipped ${e.slot}: ${e.reason}`);
    else if(e.type==='ad_committed')log(`Queued ad ${e.slot}, this decision is now fixed`);
    else if(e.type==='underrun')log('Podcast buffer underrun, recovering');
    else if(e.type==='error')fail(e.message);
    else if(e.type!=='fetch_error')log(e.type);
  }});
  if(session)player.setSession(session);return player;
}
function renderSession(){
  if(!session)return;
  $('analysisRuns').textContent=session.analysis_runs??0;$('readyAds').textContent=session.slots.filter(s=>s.status==='ready').length+' / '+session.slots.length;$('cacheStatus').textContent=session.decision_cache_hit?'Hit':'New mix';
  $('sessionState').textContent=session.status==='complete'?`${session.decision_cache_hit?'Reused':'Prepared'} in ${(session.decision_cache_hit?session.lookup_s:session.elapsed_s)?.toFixed(2)||'0'}s · episode analysis reused`:'Preparing ads in the background, podcast playback is available now';
  if(session.status==='complete'){
    const errors=session.slots.filter(s=>s.status==='error').length,skipped=session.slots.filter(s=>s.status==='skipped').length;
    $('sessionState').textContent+=` · ${session.slots.filter(s=>s.status==='ready').length} ready, ${skipped} skipped, ${errors} errors`;
  }
  $('slots').innerHTML=session.slots.map(s=>`<div class="slot"><div class="row"><b>${clock(s.cut_time)} · ${esc(s.advertiser||s.id)}</b><span class="badge">${esc(s.status)}</span></div><p class="muted">${s.status==='ready'?`${esc(s.voice)} · ${s.speed}× · ${s.duration.toFixed(1)}s · creative ${s.creative_cache_hit?'cached':'new'} · TTS ${s.tts_cache_hit?'cached':'new'}`:esc(s.reason||'Selecting and preparing a safe ad')}</p><div class="controls"><button class="small" data-jump="${Math.max(0,s.cut_time-10)}">Play from 10s before</button>${s.status==='ready'?`<button class="small" data-preview="${esc(s.url)}">Preview ad</button>`:''}</div>${s.script?`<details><summary>Script and decisions</summary><p>${esc(s.script)}</p><p class="muted">${esc(JSON.stringify(s.excluded||[]))}</p></details>`:''}</div>`).join('');
  session.slots.forEach((slot,index)=>{
    if(!slot.business_selection)return;
    const details=document.createElement('details'),summary=document.createElement('summary'),body=document.createElement('p');
    summary.textContent='Why this business';
    body.textContent=`Compared eligible businesses against ${slot.business_selection.context_word_count??'available'} preceding words · ${slot.business_selection.reason||''} ${slot.business_selection.alternatives||''}`;
    details.append(summary,body);$('slots').children[index].append(details);
  });
  if(session.agent_network&&session.status!=='complete')$('sessionState').textContent+=' · up to 3 slot teams run in parallel';
  document.querySelectorAll('[data-jump]').forEach(b=>b.onclick=async()=>{try{if(previewAudio)previewAudio.pause();await initPlayer().play(Number(b.dataset.jump))}catch(e){fail(e)}});
  document.querySelectorAll('[data-preview]').forEach(b=>b.onclick=async()=>{if(player?.running)await player.pause();if(previewAudio)previewAudio.pause();previewAudio=new Audio(b.dataset.preview);previewAudio.play().catch(fail)});
  if(player)player.setSession(session);
}
async function prepare(){
  const epoch=++sessionEpoch;clearTimeout(poller);$('error').textContent='';$('prepare').disabled=true;
  try{
    const profile=JSON.parse($('profileJson').value);const ids=[...document.querySelectorAll('[data-ad]:checked')].map(e=>e.dataset.ad);
    const value=await api('/api/live/sessions',{method:'POST',body:JSON.stringify({episode_id:library.episode.id,profile,advertiser_ids:ids,voice:$('voice').value,speed:$('speed').value,generate_missing:$('generate').checked})});
    if(epoch!==sessionEpoch)return;session=value;
    renderSession();log(session.decision_cache_hit?'Session cache hit, no generation calls':'New selection, existing episode analysis reused');
    async function poll(){if(epoch!==sessionEpoch)return;try{const value=await api('/api/live/sessions/'+session.id);if(epoch!==sessionEpoch)return;session=value;renderSession();if(session.status!=='complete')poller=setTimeout(poll,1000);else log('Ad preparation complete')}catch(e){fail(e)}}
    if(session.status!=='complete')poller=setTimeout(poll,500);
  }catch(e){fail(e)}finally{$('prepare').disabled=false}
}
$('prepare').onclick=prepare;
$('play').onclick=async()=>{try{if(previewAudio)previewAudio.pause();await initPlayer().play()}catch(e){fail(e)}};
$('pause').onclick=()=>player?.pause();
$('seek').onchange=async()=>{try{await initPlayer().play(Number($('seek').value))}catch(e){fail(e)}};
$('profile').onchange=()=>{$('profileJson').value=JSON.stringify(library.profiles.find(p=>p.id===$('profile').value),null,2)};
function chooseInventory(real){document.querySelectorAll('[data-ad]').forEach(x=>x.checked=real?library.default_advertisers.includes(x.dataset.ad):!library.default_advertisers.includes(x.dataset.ad))}
$('realBrands').onclick=()=>chooseInventory(true);$('fictionalBrands').onclick=()=>chooseInventory(false);
$('saveAdvertiser').onclick=async()=>{try{const value=JSON.parse($('advertiserJson').value);const saved=await api('/api/live/advertisers',{method:'POST',body:JSON.stringify(value)});library=await api('/api/live/library?episode='+library.episode.id);renderInventory(new Set([...document.querySelectorAll('[data-ad]:checked')].map(x=>x.dataset.ad).concat(saved.id)));log('Advertiser brief saved, changed facts invalidate only that creative and related TTS')}catch(e){fail(e)}};
function renderInventory(selected){$('inventory').innerHTML=library.advertisers.map(a=>`<label class="ad"><input type="checkbox" data-ad="${esc(a.id)}" ${selected.has(a.id)?'checked':''}><span><b>${esc(a.name)}</b><span class="muted">${esc(a.product)}</span></span></label>`).join('')}
setInterval(()=>{if(!player)return;const s=player.current();$('position').textContent=clock(s.sourceTime);if(document.activeElement!==$('seek'))$('seek').value=s.sourceTime;$('nowPlaying').textContent=s.kind==='ad'?'Advertisement':player.paused?'Paused':player.running?'Podcast':'Ready';$('buffer').textContent=`${(s.bufferedSeconds||0).toFixed(0)}s scheduled · ${player.buffers.size}/8 decoded buffers · ${player.underruns} underruns`;},250);
