"""Local voice samples and explicit podcast/advertiser-scoped synthesis grants."""
import hashlib,io,json,re,subprocess,threading,time,uuid,urllib.request,wave
from pathlib import Path
from gemini_review import load_env
from gnani_tts_ads import normalize_wav,spoken_text
from live_cache import read,write_json,digest,ROOT

class VoiceLibrary:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self.path=self.root/'voices.json';self.items=read(self.path) if self.path.exists() else {};self.private_path=self.root/'private_assets.json';self.private=read(self.private_path) if self.private_path.exists() else {};self.api_lock=threading.Lock()
    def save(self):write_json(self.path,self.items)
    def public(self):return [{k:v for k,v in item.items() if k not in {'embedding_path','sample_path','reference_path'}} for item in self.items.values()]
    def epoch(self):return digest([{k:v for k,v in i.items() if k in {'id','active','revision','status','episode_ids','advertiser_ids'}} for i in self.items.values()])
    def add(self,metadata,sample_path):
        if metadata.get('rights_confirmed') is not True:raise ValueError('Confirm authorization from the speaker and permission to synthesize ads')
        if metadata.get('owner_type') not in {'brand','host'}:raise ValueError('Choose brand or host')
        for key in ['name','speaker','authorized_by']:
            if not isinstance(metadata.get(key),str) or not 1<=len(metadata[key].strip())<=200:raise ValueError('Enter '+key)
        episodes=metadata.get('episode_ids',[]);ads=metadata.get('advertiser_ids',[])
        if not episodes or not ads or not all(isinstance(v,str) for v in episodes+ads):raise ValueError('Choose permitted podcasts and advertisers')
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(sample_path)],capture_output=True,text=True)
        if probe.returncode:raise ValueError('Cannot read voice sample')
        duration=float(json.loads(probe.stdout)['format']['duration'])
        if not 5<=duration<=30.1:raise ValueError('Use a clean voice sample between 5 and 30 seconds')
        vid=uuid.uuid4().hex[:20];directory=self.root/vid;directory.mkdir();original=directory/('sample'+Path(sample_path).suffix);Path(sample_path).replace(original)
        reference=directory/'reference.wav';result=subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(original),'-ar','24000','-ac','1','-c:a','pcm_s16le',str(reference)],capture_output=True)
        if result.returncode:raise ValueError('Sample conversion failed')
        item={'id':vid,'name':metadata['name'].strip(),'speaker':metadata['speaker'].strip(),'owner_type':metadata['owner_type'],'authorized_by':metadata['authorized_by'].strip(),'permission_reference':str(metadata.get('permission_reference',''))[:1000],'episode_ids':sorted(set(episodes)),'advertiser_ids':sorted(set(ads)),'created_at':time.time(),'consent_at':time.time(),'revision':1,'active':True,'status':'sample_uploaded','duration_s':duration,'sample_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),'sample_path':str(original),'reference_path':str(reference),'rights_attestation':True,'identity_verification':'Local operator attestation only, not independently verified','provider_model':'vachana-vc-v1'}
        item['history']=[{'action':'grant','at':time.time(),'authorized_by':item['authorized_by'],'episode_ids':item['episode_ids'],'advertiser_ids':item['advertiser_ids']}]
        with self.lock:self.items[vid]=item;self.save()
        return {k:v for k,v in item.items() if not k.endswith('_path')}
    def grant(self,vid,metadata):
        with self.lock:
            item=self.items[vid]
            if metadata.get('rights_confirmed') is not True:raise ValueError('Confirm the updated voice authorization')
            episodes=metadata.get('episode_ids',[]);ads=metadata.get('advertiser_ids',[])
            if not episodes or not ads or not all(isinstance(x,str) for x in episodes+ads):raise ValueError('Select explicit podcasts and advertisers')
            if not str(metadata.get('authorized_by',item['authorized_by'])).strip():raise ValueError('Record who authorizes this permission')
            item.update(episode_ids=sorted(set(episodes)),advertiser_ids=sorted(set(ads)),active=True,revision=item['revision']+1,consent_at=time.time(),authorized_by=str(metadata.get('authorized_by',item['authorized_by']))[:200]);self.save()
            item.setdefault('history',[]).append({'action':'grant','at':time.time(),'authorized_by':item['authorized_by'],'episode_ids':item['episode_ids'],'advertiser_ids':item['advertiser_ids']});self.save()
        return self.public()
    def revoke(self,vid):
        with self.lock:
            self.items[vid]['active']=False;self.items[vid]['revision']+=1;self.items[vid].setdefault('history',[]).append({'action':'revoke','at':time.time()});self.save()
    def authorize(self,vid,episode,advertiser,ready=True):
        item=self.items.get(vid)
        if not item or not item['active'] or episode not in item['episode_ids'] or advertiser not in item['advertiser_ids']:raise PermissionError('Voice is not authorized for this podcast and advertiser')
        if ready and item['status']!='ready':raise ValueError('Create the voice embedding before using this sample')
        return item
    def embed(self,vid):
        item=self.items[vid]
        if not item['active']:raise PermissionError('Voice permission was revoked')
        if item['status']=='ready':return
        with self.api_lock:
            if not item['active']:raise PermissionError('Voice permission was revoked')
            if item['status']=='ready':return
            env=load_env(ROOT/'.env');key=env.get('GNANI_API_KEY','')
            if not key:raise ValueError('GNANI_API_KEY is missing from the local .env')
            boundary='----voice'+uuid.uuid4().hex;data=Path(item['reference_path']).read_bytes();body=(f'--{boundary}\r\nContent-Disposition: form-data; name="audio_file"; filename="reference.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()+data+f'\r\n--{boundary}--\r\n'.encode()
            request=urllib.request.Request('https://api.vachana.ai/api/v1/tts/voice-clone/embeddings',data=body,headers={'X-API-Key-ID':key,'Content-Type':'multipart/form-data; boundary='+boundary,'User-Agent':'GnaniPodcastTTS/1.0'})
            start=time.perf_counter()
            with urllib.request.urlopen(request,timeout=180) as response:payload=json.load(response)
            embedding=payload.get('data',{}).get('voice_clone_embedding')
            if not payload.get('success') or not isinstance(embedding,dict) or not embedding.get('embedding') or not embedding.get('shape') or not embedding.get('dtype'):raise RuntimeError('Provider returned no valid voice embedding')
            path=self.root/vid/'embedding.json';write_json(path,embedding)
            with self.lock:item.update(status='ready',embedding_path=str(path),embedding_seconds=round(time.perf_counter()-start,6));self.save()
    def synthesize(self,vid,episode,advertiser,text,speed,destination):
        item=self.authorize(vid,episode,advertiser);destination=Path(destination)
        if not .85<=speed<=1:raise ValueError('Voice speed must stay between 0.85 and 1.0')
        embedding=read(item['embedding_path']);parts=[p.strip(' ,') for p in spoken_text(text).split('<pauses>') if p.strip(' ,')];pcm=[];calls=0;started=time.perf_counter();key=load_env(ROOT/'.env').get('GNANI_API_KEY','')
        # Cloning has no documented Timbre-tag support: render beats independently and insert silence locally
        with self.api_lock:
            for index,part in enumerate(parts):
                self.authorize(vid,episode,advertiser)
                pkey=digest({'voice':vid,'sample':item['sample_sha256'],'model':'vachana-vc-v1','text':part});path=self.root/vid/'beats'/(pkey+'.wav')
                if not path.exists():
                    if not key:raise ValueError('GNANI_API_KEY is missing')
                    body={'text':part,'model':'vachana-vc-v1','speaker_embedding':embedding,'audio_config':{'sample_rate':44100,'num_channels':1,'sample_width':2,'encoding':'linear_pcm','container':'wav'}}
                    request=urllib.request.Request('https://api.vachana.ai/api/v1/tts/inference',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-API-Key-ID':key,'User-Agent':'GnaniPodcastTTS/1.0'})
                    with urllib.request.urlopen(request,timeout=180) as response:data=normalize_wav(response.read())
                    path.parent.mkdir(exist_ok=True);path.write_bytes(data);calls+=1
                with wave.open(str(path),'rb') as wav:
                    if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(44100,1,2):raise ValueError('Unexpected cloned audio format')
                    pcm.append(wav.readframes(wav.getnframes()))
                if index<len(parts)-1:pcm.append(b'\0'*(round(.35*44100)*2))
        intermediate=destination.with_suffix('.clone.wav');destination.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(intermediate),'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(44100);wav.writeframes(b''.join(pcm))
        result=subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(intermediate),'-af',f'atempo={speed}','-ar','48000','-ac','1','-c:a','pcm_s16le',str(destination)],capture_output=True);intermediate.unlink(missing_ok=True)
        if result.returncode:raise ValueError('Cloned audio rendering failed')
        self.authorize(vid,episode,advertiser)
        return {'model':'vachana-vc-v1','provider_calls':calls,'seconds':round(time.perf_counter()-started,6),'pause_handling':'350ms local silence between rendered beats','speed_handling':'Local pitch-preserving tempo adjustment'}
    def protect(self,asset_key,vid,episode,advertiser):
        with self.lock:self.private[asset_key]={'voice_id':vid,'episode_id':episode,'advertiser_id':advertiser};write_json(self.private_path,self.private)
    def allow_asset(self,asset_key,episode,advertiser=None):
        info=self.private[asset_key]
        self.authorize(info['voice_id'],episode,advertiser or info['advertiser_id'])
