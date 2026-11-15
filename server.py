"""Loopback-only HTML app. No audio processing runs on the local machine."""
import argparse
import json
import mimetypes
from pathlib import Path
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from kaggle_job import Job, preflight, verify_auth

ROOT=Path(__file__).resolve().parent
JOBS=ROOT/'jobs'
TOKEN=secrets.token_urlsafe(32)
REGISTRY={}
ALLOWED_AUDIO={'.mp3','.wav','.m4a','.flac','.ogg','.aac','.mp4','.opus'}
MAX_UPLOAD=2*1024**3


class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):
        # Avoid dumping request metadata or local authentication headers.
        pass

    def send_json(self,value,status=200):
        body=json.dumps(value).encode()
        self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(body)

    def guarded(self):
        expected=f'{self.server.server_address[0]}:{self.server.server_address[1]}'
        if self.headers.get('Host') not in {expected,f'localhost:{self.server.server_address[1]}'}:
            self.send_json({'error':'Invalid host'},403);return False
        if not secrets.compare_digest(self.headers.get('X-App-Token',''),TOKEN):
            self.send_json({'error':'Reload the app page before submitting'},403);return False
        return True

    def read_json(self):
        length=int(self.headers.get('Content-Length',0))
        if not 0<length<65536: raise ValueError('Invalid JSON request size')
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        path=urlparse(self.path).path
        try:
            if path=='/':
                page=(ROOT/'web/index.html').read_text(encoding='utf-8').replace('__APP_TOKEN__',TOKEN)
                body=page.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
                self.end_headers();self.wfile.write(body);return
            if path=='/api/config':
                self.send_json(preflight());return
            if path=='/api/jobs':
                self.send_json([job.snapshot() for job in REGISTRY.values()]);return
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{12})',path)
            if match:
                self.send_json(REGISTRY[match[1]].snapshot());return
            match=re.fullmatch(r'/files/([a-f0-9]{12})/(.+)',path)
            if match:
                directory=JOBS/match[1]
                name=unquote(match[2])
                target=(directory/'results.zip') if name=='results.zip' else directory/'result'/name
                base=directory.resolve()
                if not target.resolve().is_relative_to(base) or not target.is_file():
                    self.send_error(404);return
                mime=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                self.send_response(200);self.send_header('Content-Type',mime)
                if target.suffix=='.zip':self.send_header('Content-Disposition','attachment; filename="podcast-results.zip"')
                self.send_header('Content-Length',str(target.stat().st_size));self.end_headers()
                with target.open('rb') as f:
                    while chunk:=f.read(1024*1024):self.wfile.write(chunk)
                return
            self.send_error(404)
        except (KeyError,FileNotFoundError):self.send_error(404)
        except (BrokenPipeError,ConnectionResetError):pass

    def do_POST(self):
        if not self.guarded():return
        path=urlparse(self.path).path
        try:
            if path=='/api/check':
                self.send_json(verify_auth());return
            if path=='/api/jobs':
                data=self.read_json()
                username=data.get('username','').strip()
                if not re.fullmatch(r'[a-zA-Z0-9_-]{3,50}',username):raise ValueError('Enter a valid Kaggle username')
                extension=Path(data.get('filename','')).suffix.lower()
                if extension not in ALLOWED_AUDIO:raise ValueError('Choose an audio file in a supported format')
                if data.get('asr_model','small') not in {'small','medium','large-v3'}:raise ValueError('Invalid ASR model')
                if data.get('rights_confirmed') is not True:raise ValueError('Confirm that you can process this recording on Kaggle')
                job_id=secrets.token_hex(6);directory=JOBS/job_id
                (directory/'input').mkdir(parents=True)
                metadata={'username':username,'original_filename':Path(data['filename']).name,
                          'audio_file':'episode'+extension,'asr_model':data.get('asr_model','small')}
                job=Job(directory,metadata);REGISTRY[job_id]=job
                self.send_json(job.snapshot(),201);return
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{12})/run',path)
            if match:
                job=REGISTRY[match[1]]
                with job.lock:
                    if job.state['status']!='awaiting_upload':raise ValueError('Job already submitted')
                    if not (job.directory/'input'/job.metadata['audio_file']).exists():raise ValueError('Audio upload is missing')
                    job.update(browser_upload_s=time.time()-job.state.get('upload_started',time.time()),status='starting')
                    job.thread=threading.Thread(target=job.run,daemon=True);job.thread.start()
                self.send_json(job.snapshot(),202);return
            self.send_error(404)
        except Exception as error:self.send_json({'error':str(error)},400)

    def do_PUT(self):
        if not self.guarded():return
        try:
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{12})/(audio|transcript)',urlparse(self.path).path)
            if not match:raise ValueError('Unknown upload route')
            job=REGISTRY[match[1]]
            if job.state['status']!='awaiting_upload':raise ValueError('Cannot replace inputs after submission')
            length=int(self.headers.get('Content-Length',0))
            if not 0<length<=MAX_UPLOAD:raise ValueError('File must be between 1 byte and 2 GiB')
            if match[2]=='transcript' and length>100*1024**2:raise ValueError('Transcript exceeds 100 MiB')
            if 'upload_started' not in job.state:job.update(upload_started=time.time())
            filename=job.metadata['audio_file'] if match[2]=='audio' else 'transcript.json'
            destination=job.directory/'input'/filename
            partial=destination.with_suffix(destination.suffix+'.partial')
            with partial.open('wb') as f:
                remaining=length
                while remaining:
                    block=self.rfile.read(min(remaining,1024*1024))
                    if not block:raise ValueError('Upload disconnected')
                    f.write(block);remaining-=len(block)
            if match[2]=='transcript':
                transcript=json.loads(partial.read_text(encoding='utf-8-sig'))
                if not isinstance(transcript.get('segments'),list):raise ValueError('Transcript must have segments[]')
            partial.replace(destination)
            job.update(message=match[2].capitalize()+' uploaded locally.')
            self.send_json({'uploaded':True})
        except Exception as error:self.send_json({'error':str(error)},400)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=5087)
    args=parser.parse_args();JOBS.mkdir(exist_ok=True)
    for path in JOBS.glob('*/state.json'):
        if not re.fullmatch(r'[a-f0-9]{12}',path.parent.name):
            continue
        state=json.loads(path.read_text())
        job=Job.__new__(Job);job.directory=path.parent;job.state=state
        job.metadata={key:state[key] for key in ['username','original_filename','audio_file','asr_model']}
        job.lock=threading.RLock();job.thread=None
        if state['status'] in {'starting','running'}:
            job.update(status='interrupted',message='Local server restarted. The Kaggle run may still exist; inspect its notebook URL. Submit a new job to run again.')
        REGISTRY[state['id']]=job
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Podcast Slots: http://127.0.0.1:{args.port}',flush=True)
    print('Local orchestration only. Podcast computation runs on Kaggle.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:server.server_close()


if __name__=='__main__':main()
