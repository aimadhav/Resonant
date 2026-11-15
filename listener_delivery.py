"""Prepare a listener-facing MP3 from an approved operator session."""
import json,shutil,subprocess,sys,threading,time
from pathlib import Path
from live_cache import ROOT,read,write_json
from gnani_tts_ads import inspect_audio

class ListenerDelivery:
    def __init__(self):
        self.root=ROOT/'cache/live/listener';self.path=self.root/'deliveries.json';self.lock=threading.Lock()
        self.entries=read(self.path) if self.path.exists() else {}
        for entry in self.entries.values():
            if entry.get('status')=='publishing':entry.update(status='interrupted',message='Publishing was interrupted, publish the session again')
    def get(self,episode):return self.entries.get(episode,{})
    def start(self,lib,session):
        if session.get('status')!='complete':raise ValueError('Wait for ad preparation to finish')
        ready=[s for s in session['slots'] if s['status']=='ready']
        if not ready:raise ValueError('This session has no approved ads to publish')
        if any(s.get('clone_voice_id') for s in ready):raise ValueError('Publishing downloadable custom-voice mixes is not enabled, use permission-scoped live playback for custom voices')
        with self.lock:
            prior=self.entries.get(lib.episode_id,{})
            if prior.get('status')=='publishing':return self.public(lib.episode_id)
            if prior.get('status')=='ready' and prior.get('session_id')==session['id'] and self.file(lib.episode_id):return self.public(lib.episode_id)
            folder=self.root/lib.episode_id/session['id'];folder.mkdir(parents=True,exist_ok=True)
            self.entries[lib.episode_id]={'status':'publishing','session_id':session['id'],'message':'Preparing the listener edition','previous_file':prior.get('file') or prior.get('previous_file')};write_json(self.path,self.entries)
            threading.Thread(target=self._run,args=(lib,session,folder),daemon=True).start()
            return self.public(lib.episode_id)
    def public(self,episode):return {k:v for k,v in self.get(episode).items() if k not in {'file','previous_file'}}
    def file(self,episode):
        item=self.get(episode);value=item.get('file') if item.get('status')=='ready' else item.get('previous_file')
        return Path(value) if value and Path(value).exists() else None
    def _run(self,lib,session,folder):
        started=time.perf_counter()
        try:
            results=[];manifest=[];audio=folder/'audio';audio.mkdir(exist_ok=True)
            for slot in session['slots']:
                if slot['status']!='ready':continue
                raw=lib.root/'tts'/lib.tts_key(slot['script'],slot['voice'],slot['speed'])/'raw.wav'
                if not raw.exists():raise ValueError('Prepared audio is unavailable, regenerate this session')
                filename=slot['id']+'.wav';shutil.copyfile(raw,audio/filename)
                results.append({'scenario_id':slot['id'],'selected_context':{'cut_time':slot['cut_time']}})
                manifest.append({'scenario_id':slot['id'],'status':'complete','voice':slot['voice'],'speed':slot['speed'],'filename':filename,'audio':inspect_audio(raw.read_bytes())})
            write_json(folder/'results.json',results);write_json(audio/'manifest.json',manifest);write_json(folder/'insertion_selection.json',{'scenario_ids':[r['scenario_id'] for r in results],'reason':'Operator-published approved session'})
            with (folder/'publish.log').open('w',encoding='utf-8') as log:
                subprocess.run([sys.executable,str(ROOT/'stitch_podcast_ads.py'),'--source',str(lib.source),'--root',str(folder),'--work',str(folder/'scratch')],stdout=log,stderr=log,check=True,timeout=3600)
            summary=read(folder/'stitch_summary.json')
            with self.lock:
                self.entries[lib.episode_id].update(status='ready',message='Listener edition is ready',file=str(folder/'podcast-with-ads.mp3'),duration=summary['output_duration_s'],published_at=time.time(),publish_seconds=round(time.perf_counter()-started,3));write_json(self.path,self.entries)
        except Exception:
            with self.lock:self.entries[lib.episode_id].update(status='failed',message='Listener export failed, see the local publishing log');write_json(self.path,self.entries)
