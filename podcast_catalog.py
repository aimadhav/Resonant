"""Uploaded podcast catalog and Kaggle-to-reviewed-library orchestration."""
import hashlib,json,os,re,shutil,subprocess,sys,threading,time,uuid
from pathlib import Path
from live_cache import Library,ROOT,read,write_json,file_hash

class PodcastCatalog:
    def __init__(self,default,voices):
        self.default=default;self.voices=voices;self.root=default.root/'podcasts';self.root.mkdir(exist_ok=True);self.path=self.root/'catalog.json';self.lock=threading.RLock();self.entries=read(self.path) if self.path.exists() else {};self.libraries={};self.versions={};self.jobs={}
        if default.source.is_file():
            prior=self.entries.get(default.episode_id,{})
            default.title=prior.get('title',getattr(default,'title',default.source.stem));filename=prior.get('filename',default.source.name);owned=self.root/default.episode_id/('episode'+default.source.suffix);owned.parent.mkdir(exist_ok=True)
            if not owned.exists():
                try:os.link(default.source,owned)
                except OSError:shutil.copyfile(default.source,owned)
            default.source=owned
            self.entries[default.episode_id]={'id':default.episode_id,'title':default.title,'filename':filename,'source':str(default.source),'sha256':file_hash(default.source),'duration':default.duration,'status':'ready','message':'Previously analyzed and reviewed episode','prepared_default':True}
            self.libraries[default.episode_id]=default;self.versions[(default.episode_id,default.chunk_set_id)]=default
        default.voices=voices
        for entry in self.entries.values():
            if entry.get('status') in {'analyzing','reviewing'}:entry.update(status='interrupted',message='Server restarted, resume processing to reuse completed outputs or retry the remote job')
        self.save()
    def save(self):write_json(self.path,self.entries)
    def public(self):
        results=[]
        for item in self.entries.values():
            row={k:v for k,v in item.items() if k not in {'source','analysis_dir','review_dir'}}
            if item['id'] in self.jobs:row['job']=self.jobs[item['id']].snapshot()
            results.append(row)
        return results
    def upload(self,stream,length,filename):
        suffix=Path(filename).suffix.lower()
        if suffix not in {'.mp3','.wav','.m4a','.flac','.ogg','.aac','.mp4','.opus'}:raise ValueError('Unsupported podcast audio format')
        if not 0<length<=2*1024**3:raise ValueError('Podcast must be between 1 byte and 2 GiB')
        temp=self.root/(uuid.uuid4().hex+'.upload');h=hashlib.sha256()
        try:
            with temp.open('wb') as f:
                remaining=length
                while remaining:
                    block=stream.read(min(1024*1024,remaining))
                    if not block:raise ValueError('Upload disconnected')
                    h.update(block);f.write(block);remaining-=len(block)
            checksum=h.hexdigest()
            for entry in self.entries.values():
                if entry['sha256']==checksum:temp.unlink();return {**entry,'upload_cache_hit':True}
            probe=subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_entries','format=duration:stream=codec_name','-of','json',str(temp)],capture_output=True,text=True)
            data=json.loads(probe.stdout) if probe.returncode==0 else {}
            duration=float(data.get('format',{}).get('duration',0))
            if not data.get('streams') or not 0<duration<=24*3600:raise ValueError('No valid audio stream or unsupported duration')
            pid=checksum[:24];directory=self.root/pid;directory.mkdir(exist_ok=True);destination=directory/('episode'+suffix);temp.replace(destination)
            entry={'id':pid,'title':Path(filename).stem[:240],'filename':Path(filename).name[:255],'source':str(destination),'sha256':checksum,'duration':duration,'status':'uploaded','created':time.time(),'message':'Ready to play, analyze on Kaggle to find ad opportunities'}
            with self.lock:self.entries[pid]=entry;self.save()
            return {**entry,'upload_cache_hit':False}
        except BaseException:temp.unlink(missing_ok=True);raise
    def library(self,pid=None):
        pid=pid or (self.default.episode_id if self.default.episode_id in self.entries else next(iter(self.entries),None))
        if pid is None:return self.default
        if pid not in self.entries:raise ValueError('Unknown podcast')
        with self.lock:
            if pid not in self.libraries:
                self.libraries[pid]=Library.from_podcast(self.entries[pid],self.default,self.voices);self.versions[(pid,self.libraries[pid].chunk_set_id)]=self.libraries[pid]
            return self.libraries[pid]
    def all_libraries(self):return list({id(v):v for v in list(self.libraries.values())+list(self.versions.values())}.values())
    def analyze(self,pid,rights,username='',asr_model='small',backend='local',device='auto'):
        if rights is not True:raise ValueError('Confirm permission to process the episode and send transcript context to Gemini')
        if backend not in {'local','kaggle'}:raise ValueError('Choose local or Kaggle processing')
        if device not in {'auto','cuda','cpu'}:raise ValueError('Choose auto, cuda or cpu device')
        if asr_model not in {'small','medium','large-v3'}:raise ValueError('Invalid transcription model')
        if backend=='kaggle' and not re.fullmatch(r'[a-zA-Z0-9_-]{3,50}',username):raise ValueError('Enter your Kaggle username')
        if backend=='local':
            from local_job import check_runtime
            check_runtime(device)
        item=self.entries[pid]
        with self.lock:
            if item['status'] in {'analyzing','reviewing','ready'}:return item
            item.update(status='analyzing',message='Starting local processing' if backend=='local' else 'Starting private Kaggle processing',processing_backend=backend);self.save()
        threading.Thread(target=self._run,args=(pid,username,asr_model,backend,device),daemon=True).start();return item
    def _run(self,pid,username,asr_model,backend='kaggle',device='auto'):
        from kaggle_job import Job
        import server as offline
        item=self.entries[pid];started=time.perf_counter()
        try:
            result_dir=Path(item.get('analysis_dir','')) if item.get('analysis_dir') else None
            if not result_dir or not (result_dir/'worker_status.json').exists() or read(result_dir/'worker_status.json').get('status')!='complete':
                job_id=uuid.uuid4().hex[:12];directory=ROOT/'jobs'/job_id;(directory/'input').mkdir(parents=True)
                source=Path(item['source']);name='episode'+source.suffix;dest=directory/'input'/name
                try:os.link(source,dest)
                except OSError:shutil.copyfile(source,dest)
                metadata={'username':username,'original_filename':item['filename'],'audio_file':name,'asr_model':asr_model,'device':device}
                if backend=='local':
                    from local_job import LocalJob
                    job=LocalJob(directory,metadata)
                else:job=Job(directory,metadata)
                self.jobs[pid]=job;offline.REGISTRY[job_id]=job
                item.update(job_id=job_id,analysis_dir=str(directory/'result'));self.save();job.run()
                if job.state['status']!='complete':raise RuntimeError(job.state.get('message','Kaggle processing failed'))
                result_dir=directory/'result'
            item.update(status='reviewing',message='Episode analysis cached, reviewing candidate boundaries with Gemini');self.save()
            review_dir=self.root/pid/'boundary-review';review_dir.mkdir(exist_ok=True)
            # Existing review outputs are fingerprinted and resumed by the boundary-review CLI
            process=subprocess.run([sys.executable,str(ROOT/'gemini_batch_review.py'),'--source',str(result_dir),'--out',str(review_dir),'--env',str(ROOT/'.env')],capture_output=True,text=True,timeout=3600)
            if process.returncode:raise RuntimeError('Boundary review did not finish, cached analysis retained for retry')
            if not (review_dir/'accepted_context_packets.json').exists():
                packets=read(review_dir/'review_packets.json');verdicts={r['slot_id']:r for r in read(review_dir/'reviews.json')};accepted=[dict(p,boundary_review=verdicts[p['slot_id']]) for p in packets if verdicts.get(p['slot_id'],{}).get('decision')=='accept'];write_json(review_dir/'accepted_context_packets.json',accepted)
            accepted_count=len(read(review_dir/'accepted_context_packets.json'))
            item.update(status='ready',message='Analysis and reviewed ad contexts cached' if accepted_count else 'Analysis cached, no approved ad breaks found, playback continues without ads',review_dir=str(review_dir),processing_seconds=round(time.perf_counter()-started,6));self.save()
            with self.lock:self.libraries.pop(pid,None)
        except Exception as error:
            item.update(status='failed',message=str(error)[:500],processing_seconds=round(time.perf_counter()-started,6));self.save()
