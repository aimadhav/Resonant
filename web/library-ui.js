/* Podcast uploads and consent-scoped voice samples for the local demo. */
let podcasts=[],voices=[],voiceEpoch=null,editingVoice=null;
async function loadEpisode(id,preserve=false){
  const previous=player?.current().sourceTime||0,wasRunning=player?.running;
  if(player){player.destroy();await context.close();player=null;context=null;}
  if(previewAudio)previewAudio.pause();sessionEpoch++;clearTimeout(poller);session=null;
  const selected=new Set([...document.querySelectorAll('[data-ad]:checked')].map(x=>x.dataset.ad));
  id=id||localStorage.getItem('intervals-studio-episode')||podcasts.find(p=>p.id==='a38cbd96e85853668d05e998')?.id;
  if(id&&!podcasts.some(p=>p.id===id))id=null;
  library=await api('/api/live/library'+(id?'?episode='+id:''));$('episodeSelect').value=library.episode.id;localStorage.setItem('intervals-studio-episode',library.episode.id);
  $('episodeTitle').textContent=library.episode.title;$('seek').max=library.episode.duration;$('seek').value=preserve?previous:0;$('position').textContent=clock(preserve?previous:0);$('buffer').textContent='No audio decoded yet';$('nowPlaying').textContent='Ready';
  const oldProfile=$('profile').value;$('profile').innerHTML=library.profiles.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');if(library.profiles.some(p=>p.id===oldProfile))$('profile').value=oldProfile;
  $('profileJson').value=JSON.stringify(library.profiles.find(p=>p.id===$('profile').value)||library.profiles[0],null,2);renderInventory(selected.size?selected:new Set(library.default_advertisers));renderVoiceScopes();updateVoiceChoices();renderPodcastStatus();$('slots').innerHTML='<p class="muted">Choose your advertisers, then prepare an ad experience to see placement decisions.</p>';$('sessionState').textContent=podcasts.length?'Ready to prepare · existing episode analysis stays cached':'Add your first episode in Episodes';$('readyAds').textContent='—';$('cacheStatus').textContent='Ready';$('error').textContent='';for(const control of ['prepare','play','pause'])$(control).disabled=!podcasts.length;if(!podcasts.length)$('analyzePodcast').disabled=true;
  if(preserve&&wasRunning)await initPlayer().play(previous);
}
async function refreshPodcasts(){
  const prior=$('episodeSelect').value;podcasts=await api('/api/podcasts');const html=podcasts.map(p=>`<option value="${esc(p.id)}">${esc(p.title)} · ${esc(p.status)}</option>`).join('');
  if($('episodeSelect').innerHTML!==html){$('episodeSelect').innerHTML=html;if(podcasts.some(p=>p.id===prior))$('episodeSelect').value=prior;else if(library)$('episodeSelect').value=library.episode.id;}
  renderPodcastStatus();if(library)renderVoiceScopes();
}
function renderPodcastStatus(){
  const entry=podcasts.find(p=>p.id===(library?.episode.id||$('episodeSelect').value));if(!entry)return;
  $('podcastStatus').textContent=entry.status+' · '+entry.message+(entry.job?' · '+entry.job.stage:'');$('analyzePodcast').disabled=['analyzing','reviewing'].includes(entry.status);$('analyzePodcast').textContent=entry.status==='ready'?'Load reviewed ad opportunities':'Analyze episode';
}
$('episodeSelect').onchange=()=>loadEpisode($('episodeSelect').value).catch(fail);
function binaryUpload(url,file,headers={},progress=()=>{}){
  return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST',url);xhr.setRequestHeader('X-App-Token',TOKEN);xhr.setRequestHeader('X-Filename',encodeURIComponent(file.name));Object.entries(headers).forEach(([k,v])=>xhr.setRequestHeader(k,v));xhr.upload.onprogress=e=>progress(e.lengthComputable?Math.round(e.loaded/e.total*100):0);xhr.onerror=()=>reject(Error('Upload disconnected'));xhr.onload=()=>{let value;try{value=JSON.parse(xhr.responseText)}catch{reject(Error('Invalid server response'));return}if(xhr.status>=400)reject(Error(value.error||'Upload failed'));else resolve(value)};xhr.send(file)});
}
$('uploadPodcast').onclick=async()=>{
  const file=$('podcastFile').files[0];if(!file)return fail('Choose a podcast audio file');$('uploadPodcast').disabled=true;
  try{const item=await binaryUpload('/api/podcasts/upload',file,{},n=>$('podcastUploadStatus').textContent='Uploading '+n+'%');await refreshPodcasts();await loadEpisode(item.id);$('podcastUploadStatus').textContent=item.upload_cache_hit?'Existing podcast recognized, cached results reused':'Uploaded, ready to play';log('Podcast added, analysis was not automatically rerun')}catch(e){fail(e)}finally{$('uploadPodcast').disabled=false}
};
$('analyzePodcast').onclick=async()=>{
  try{const entry=podcasts.find(p=>p.id===library.episode.id);if(entry?.status==='ready'){await loadEpisode(entry.id,true);return}
    await api('/api/podcasts/'+library.episode.id+'/analyze',{method:'POST',body:JSON.stringify({rights_confirmed:$('podcastRights').checked,username:$('kaggleUser').value,asr_model:$('asrModel').value,backend:$('processingBackend').value,device:$('processingDevice').value})});await refreshPodcasts();log('Episode analysis started on '+$('processingBackend').value+', playback remains available')
  }catch(e){fail(e)}
};
function renderVoiceScopes(episodeIds=null,advertiserIds=null){
  const ep=new Set(episodeIds||[...document.querySelectorAll('[data-voice-episode]:checked')].map(x=>x.dataset.voiceEpisode));if(!ep.size&&library&&!editingVoice)ep.add(library.episode.id);
  const ads=new Set(advertiserIds||[...document.querySelectorAll('[data-voice-ad]:checked')].map(x=>x.dataset.voiceAd));
  $('voiceScopeEpisodes').innerHTML=podcasts.map(p=>`<label class="ad"><input type="checkbox" data-voice-episode="${esc(p.id)}" ${ep.has(p.id)?'checked':''}><span>${esc(p.title)}</span></label>`).join('');
  $('voiceScopeAdvertisers').innerHTML=library.advertisers.map(a=>`<label class="ad"><input type="checkbox" data-voice-ad="${esc(a.id)}" ${ads.has(a.id)?'checked':''}><span>${esc(a.name)}</span></label>`).join('');
}
function updateVoiceChoices(){
  const prior=$('voice').value;$('voice').innerHTML='<option value="auto">Reuse original choice</option><option value="authorized">Use an authorized brand/host voice</option><option>Riyaa</option><option>Shivani</option>'+voices.filter(v=>v.active&&v.status==='ready'&&v.episode_ids.includes(library.episode.id)).map(v=>`<option value="clone:${v.id}">${esc(v.name)} · ${esc(v.owner_type)}</option>`).join('');
  if([...$('voice').options].some(o=>o.value===prior))$('voice').value=prior;
}
async function refreshVoices(){
  const data=await api('/api/voices');const changed=voiceEpoch!==null&&voiceEpoch!==data.permission_epoch;voiceEpoch=data.permission_epoch;voices=data.voices;if(!library)return;
  updateVoiceChoices();$('voiceList').innerHTML=voices.length?voices.map(v=>`<div class="slot"><b>${esc(v.name)}</b><p class="muted">${esc(v.owner_type)} · ${esc(v.speaker)} · ${v.active?esc(v.status):'permission revoked'}<br>${v.episode_ids.length} podcast(s), ${v.advertiser_ids.length} advertiser(s)</p><div class="controls">${v.active&&v.status!=='ready'?`<button class="small" data-activate-voice="${v.id}">Create voice with Gnani</button>`:''}<button class="small" data-edit-voice="${v.id}">Edit permissions</button>${v.active?`<button class="small" data-revoke-voice="${v.id}">Revoke use</button>`:''}</div></div>`).join(''):'<p class="muted">No custom voice samples yet</p>';
  document.querySelectorAll('[data-activate-voice]').forEach(b=>b.onclick=async()=>{b.disabled=true;$('voiceStatus').textContent='Sending the authorized reference sample to Gnani to create the reusable voice embedding';try{await api('/api/voices/'+b.dataset.activateVoice+'/activate',{method:'POST',body:JSON.stringify({send_to_gnani:true})});await refreshVoices();$('voiceStatus').textContent='Voice ready for its permitted podcasts and advertisers'}catch(e){fail(e)}finally{b.disabled=false}});
  document.querySelectorAll('[data-revoke-voice]').forEach(b=>b.onclick=async()=>{try{await api('/api/voices/'+b.dataset.revokeVoice+'/revoke',{method:'POST',body:'{}'});await refreshVoices();log('Voice use revoked, cached custom audio now requires a new permission grant')}catch(e){fail(e)}});
  document.querySelectorAll('[data-edit-voice]').forEach(b=>b.onclick=()=>editVoice(b.dataset.editVoice));
  if(changed&&session?.slots.some(s=>s.clone_voice_id)&&player){const pos=player.current().sourceTime,wasRunning=player.running;player.seek(pos);await prepare();if(wasRunning)await player.play(pos);log('Voice permissions changed, queued custom voice audio was rebuilt')}
}
function editVoice(id){
  editingVoice=voices.find(v=>v.id===id);$('voiceEditor').open=true;$('voiceName').value=editingVoice.name;$('voiceSpeaker').value=editingVoice.speaker;$('voiceAuthorizer').value=editingVoice.authorized_by;$('voiceReference').value=editingVoice.permission_reference||'';$('voiceOwnerType').value=editingVoice.owner_type;$('voiceRights').checked=false;$('uploadVoice').textContent='Save permitted use';renderVoiceScopes(editingVoice.episode_ids,editingVoice.advertiser_ids);
}
$('newVoice').onclick=()=>{editingVoice=null;['voiceName','voiceSpeaker','voiceAuthorizer','voiceReference'].forEach(id=>$(id).value='');$('voiceRights').checked=false;$('uploadVoice').textContent='Save sample & permission';renderVoiceScopes([library.episode.id],[])};
let sampleObjectUrl=null;
$('voiceFile').onchange=()=>{if(sampleObjectUrl)URL.revokeObjectURL(sampleObjectUrl);const file=$('voiceFile').files[0];$('voiceFilePreview').hidden=!file;if(file){sampleObjectUrl=URL.createObjectURL(file);$('voiceFilePreview').src=sampleObjectUrl}};
$('uploadVoice').onclick=async()=>{
  $('uploadVoice').disabled=true;
  try{
    const metadata={name:$('voiceName').value,speaker:$('voiceSpeaker').value,owner_type:$('voiceOwnerType').value,authorized_by:$('voiceAuthorizer').value,permission_reference:$('voiceReference').value,rights_confirmed:$('voiceRights').checked,episode_ids:[...document.querySelectorAll('[data-voice-episode]:checked')].map(x=>x.dataset.voiceEpisode),advertiser_ids:[...document.querySelectorAll('[data-voice-ad]:checked')].map(x=>x.dataset.voiceAd)};
    if(!metadata.rights_confirmed)throw Error('Confirm the speaker authorization first');
    if(!metadata.episode_ids.length||!metadata.advertiser_ids.length)throw Error('Choose at least one permitted podcast and advertiser');
    if(editingVoice)await api('/api/voices/'+editingVoice.id+'/grant',{method:'POST',body:JSON.stringify(metadata)});
    else{const file=$('voiceFile').files[0];if(!file)throw Error('Choose a 5–30 second authorized voice sample');await binaryUpload('/api/voices/upload',file,{'X-Voice-Metadata':encodeURIComponent(JSON.stringify(metadata))},n=>$('voiceStatus').textContent='Uploading voice sample '+n+'%')}
    await refreshVoices();$('voiceRights').checked=false;$('voiceStatus').textContent=editingVoice?'Permission scope updated':'Sample saved locally, Create voice with Gnani sends the reference for embedding generation';
  }catch(e){fail(e)}finally{$('uploadVoice').disabled=false}
};
setInterval(()=>{if(podcasts.some(p=>['analyzing','reviewing'].includes(p.status)))refreshPodcasts().catch(fail)},4000);
let checkingVoices=false;
setInterval(async()=>{if(!library||checkingVoices)return;checkingVoices=true;try{await refreshVoices()}catch{}finally{checkingVoices=false}},5000);
function updateProcessingFields(){$('kaggleFields').hidden=$('processingBackend').value!=='kaggle';$('localDeviceFields').hidden=$('processingBackend').value!=='local'}
$('processingBackend').onchange=updateProcessingFields;
(async()=>{try{const config=await api('/api/app/config');$('processingBackend').value=config.processing_backend;$('kaggleUser').value=config.kaggle_username;updateProcessingFields();const example=document.querySelector('.example-strip');if(example&&!config.demo_available)example.hidden=true;await refreshPodcasts();await loadEpisode();await refreshVoices();$('advertiserJson').value=JSON.stringify({id:'demo_planner',name:'Demo Planner',product:'Undated paper planner',category:'focus_planner',attributes:['analog'],approved_claims:['The planner has an undated weekly layout.'],approved_cta:'Explore the planner details',tags:['planning']},null,2);log('Podcast library loaded, existing analysis cache retained')}catch(e){fail(e)}})();
