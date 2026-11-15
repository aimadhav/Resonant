"""Loopback demo player; preserves the existing Kaggle upload API at /upload."""
import argparse,copy,json,mimetypes,re,threading,uuid
from pathlib import Path
from urllib.parse import urlparse,parse_qs,unquote
from http.server import ThreadingHTTPServer
import server as offline
from live_cache import Library,ROOT
from voice_library import VoiceLibrary
from podcast_catalog import PodcastCatalog
from listener_delivery import ListenerDelivery
from settings import setting

LIBRARY=None
CATALOG=None
VOICES=None
DELIVERY=None
def demo_media(name):
    directory=setting('DEMO_MEDIA_DIR')
    return Path(directory).expanduser()/name if directory else None
class Handler(offline.Handler):
    def file(self,path,immutable=False):
        size=path.stat().st_size;start=0;end=size-1;status=200
        value=self.headers.get('Range')
        if value:
            m=re.fullmatch(r'bytes=(\d+)-(\d*)',value)
            if not m:self.send_error(416);return
            start=int(m[1]);end=min(int(m[2]) if m[2] else end,end)
            if start>end or start>=size:self.send_error(416);return
            status=206
        self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(str(path))[0] or 'application/octet-stream');self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
        self.send_header('Cache-Control','public, max-age=31536000, immutable' if immutable else 'no-store')
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command=='HEAD':return
        try:
            with path.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    block=f.read(min(256*1024,remaining))
                    if not block:break
                    self.wfile.write(block);remaining-=len(block)
        except (BrokenPipeError,ConnectionResetError):pass

    def do_GET(self):
        path=urlparse(self.path).path
        expected=f'{self.server.server_address[0]}:{self.server.server_address[1]}'
        if self.headers.get('Host') not in {expected,f'localhost:{self.server.server_address[1]}'}:
            self.send_json({'error':'Invalid host'},403);return
        try:
            if path in {'/','/studio','/upload'}:
                filename={'/':'listen.html','/studio':'live.html','/upload':'index.html'}[path];page=(ROOT/'web'/filename).read_text(encoding='utf-8').replace('__APP_TOKEN__',offline.TOKEN);body=page.encode()
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path in {'/player.js','/live-ui.js','/library-ui.js','/studio-ui.js','/studio-layout.js','/listen.js','/listen.css','/studio.css','/studio-editorial.css'}:self.file(ROOT/'web'/path[1:]);return
            if path=='/api/app/config':
                from local_job import processor_python
                demo=demo_media('podcast-with-ads.mp3')
                self.send_json({'processing_backend':setting('PROCESSING_BACKEND','local'),'kaggle_username':setting('KAGGLE_USERNAME'),'local_runtime_installed':processor_python().is_file(),'demo_available':bool(demo and demo.exists())});return
            match=re.fullmatch(r'/api/demo/gym/(preview|full)',path)
            if match:
                file=demo_media('transition-preview.mp3' if match[1]=='preview' else 'podcast-with-ads.mp3')
                if not file or not file.exists():self.send_error(404);return
                self.file(file);return
            if path=='/api/listen/library':
                episodes=[]
                for item in CATALOG.public():
                    duration=item['duration'];edition=DELIVERY.get(item['id']) if DELIVERY else {}
                    if edition.get('status')=='ready':duration=edition['duration']
                    elif item['id']==setting('DEMO_EPISODE_ID') and demo_media('stitch_summary.json') and demo_media('stitch_summary.json').exists():duration=json.loads(demo_media('stitch_summary.json').read_text())['output_duration_s']
                    display={'a38cbd96e85853668d05e998':('The Philosophy of Success','PGX Ideas'),'abeedd3cb579476b5f80037b':('A Neuroscientist’s Guide to Focus & Memory','Raj Shamani · Dr. Sahar Yousef')}.get(item['id'],(item['title'],''))
                    episodes.append({'id':item['id'],'title':display[0],'creator':display[1],'duration':duration,'audio_url':'/api/listen/audio/'+item['id']})
                self.send_json({'episodes':episodes});return
            match=re.fullmatch(r'/api/listen/audio/([a-f0-9]{24})',path)
            if match:
                entry=CATALOG.entries.get(match[1])
                if not entry:self.send_error(404);return
                prepared=demo_media('podcast-with-ads.mp3')
                source=(DELIVERY.file(match[1]) if DELIVERY else None) or (prepared if match[1]==setting('DEMO_EPISODE_ID') and prepared and prepared.exists() else Path(entry['source']))
                self.file(source);return
            match=re.fullmatch(r'/api/listen/publish/([a-f0-9]{24})',path)
            if match:self.send_json(DELIVERY.public(match[1]));return
            if path=='/api/podcasts':self.send_json(CATALOG.public());return
            if path=='/api/voices':self.send_json({'voices':VOICES.public(),'permission_epoch':VOICES.epoch()});return
            if path=='/api/live/library':
                episode=parse_qs(urlparse(self.path).query).get('episode',[None])[0];self.send_json(CATALOG.library(episode).public());return
            match=re.fullmatch(r'/api/live/sessions/([a-f0-9]{16})',path)
            if match:
                library=next((lib for lib in CATALOG.all_libraries() if match[1] in lib.sessions),None)
                if not library:self.send_error(404);return
                result=copy.deepcopy(library.sessions[match[1]])
                for slot in result['slots']:
                    if slot.get('clone_voice_id') and not library._voice_allowed(slot['clone_voice_id'],slot.get('advertiser_id')):slot.update(status='skipped',reason='Voice authorization revoked or no longer in scope');slot.pop('url',None)
                result['voice_permission_epoch']=VOICES.epoch();self.send_json(result);return
            match=re.fullmatch(r'/api/live/chunks/([a-f0-9]{24})/([a-f0-9]{16})/(\d+)\.wav',path)
            if match:
                if match[1] not in CATALOG.entries:self.send_error(404);return
                CATALOG.library(match[1]);library=CATALOG.versions.get((match[1],match[2]))
                if not library:self.send_error(404);return
                self.file(library.chunk(int(match[3])),True);return
            match=re.fullmatch(r'/api/live/voice-media/([a-f0-9]{16})/([a-f0-9]{64})\.wav',path)
            if match:
                library=next((lib for lib in CATALOG.all_libraries() if match[1] in lib.sessions),None)
                if not library:self.send_error(403);return
                session=library.sessions[match[1]];slot=next((s for s in session['slots'] if s.get('asset_key')==match[2] and s.get('clone_voice_id')),None)
                if not slot:self.send_error(403);return
                VOICES.allow_asset(match[2],library.episode_id,slot['advertiser_id']);self.file(library.root/'media'/(match[2]+'.wav'));return
            match=re.fullmatch(r'/api/live/media/([a-f0-9]{64})\.wav',path)
            if match:
                if match[1] in VOICES.private:self.send_error(403);return
                file=LIBRARY.root/'media'/(match[1]+'.wav')
                if not file.exists():self.send_error(404);return
                self.file(file,True);return
            return super().do_GET()
        except PermissionError as error:self.send_json({'error':str(error)[:500]},403)
        except Exception as error:self.send_json({'error':str(error)[:500]},400)

    def do_HEAD(self):self.do_GET()
    def do_POST(self):
        path=urlparse(self.path).path
        if path=='/api/listen/publish':
            if not self.guarded():return
            try:
                data=self.read_json();sid=data.get('session_id');lib=next((l for l in CATALOG.all_libraries() if sid in l.sessions),None)
                if not lib:raise ValueError('Prepare a session in this server before publishing')
                self.send_json(DELIVERY.start(lib,copy.deepcopy(lib.sessions[sid])),202)
            except Exception as error:self.send_json({'error':str(error)[:500]},400)
            return
        if path=='/api/podcasts/upload':
            if not self.guarded():return
            try:
                item=CATALOG.upload(self.rfile,int(self.headers.get('Content-Length',0)),unquote(self.headers.get('X-Filename','podcast.mp3')));self.send_json({k:v for k,v in item.items() if k!='source'},201)
            except Exception as error:self.send_json({'error':str(error)[:500]},400)
            return
        match=re.fullmatch(r'/api/podcasts/([a-f0-9]{24})/analyze',path)
        if match:
            if not self.guarded():return
            try:
                data=self.read_json();item=CATALOG.analyze(match[1],data.get('rights_confirmed'),data.get('username',setting('KAGGLE_USERNAME')),data.get('asr_model','small'),data.get('backend',setting('PROCESSING_BACKEND','local')),data.get('device','auto'));self.send_json({k:v for k,v in item.items() if k not in {'source','analysis_dir','review_dir'}},202)
            except Exception as error:self.send_json({'error':str(error)[:500]},400)
            return
        if path=='/api/voices/upload':
            if not self.guarded():return
            temp=None
            try:
                metadata=json.loads(unquote(self.headers.get('X-Voice-Metadata','{}')));self.voice_scope(metadata)
                if metadata.get('rights_confirmed') is not True:raise ValueError('Confirm authorized voice use before uploading')
                length=int(self.headers.get('Content-Length',0));suffix=Path(unquote(self.headers.get('X-Filename','sample.wav'))).suffix.lower()
                if suffix not in {'.mp3','.wav','.m4a','.flac','.ogg'} or not 0<length<=20*1024**2:raise ValueError('Use a supported voice sample under 20 MiB')
                directory=VOICES.root/'uploads';directory.mkdir(exist_ok=True);temp=directory/(uuid.uuid4().hex+suffix)
                with temp.open('wb') as f:
                    remaining=length
                    while remaining:
                        block=self.rfile.read(min(1024*1024,remaining))
                        if not block:raise ValueError('Voice sample upload disconnected')
                        f.write(block);remaining-=len(block)
                self.send_json(VOICES.add(metadata,temp),201)
            except Exception as error:
                if temp:temp.unlink(missing_ok=True)
                self.send_json({'error':str(error)[:500]},400)
            return
        match=re.fullmatch(r'/api/voices/([a-f0-9]{20})/(activate|grant|revoke)',path)
        if match:
            if not self.guarded():return
            try:
                data=self.read_json();vid,action=match.groups()
                if action=='activate':
                    if data.get('send_to_gnani') is not True:raise ValueError('Confirm sending this authorized sample to Gnani for voice cloning')
                    VOICES.embed(vid)
                elif action=='grant':self.voice_scope(data);VOICES.grant(vid,data)
                else:VOICES.revoke(vid)
                self.send_json({'voices':VOICES.public(),'permission_epoch':VOICES.epoch()})
            except Exception as error:self.send_json({'error':str(error)[:500]},400)
            return
        if urlparse(self.path).path=='/api/live/advertisers':
            if not self.guarded():return
            try:
                ad=LIBRARY.register(self.read_json())
                for library in CATALOG.all_libraries():library.ads=LIBRARY.ads;library.by_ad=LIBRARY.by_ad
                self.send_json(ad,201)
            except Exception as error:self.send_json({'error':str(error)[:500]},400)
            return
        if urlparse(self.path).path=='/api/live/sessions':
            if not self.guarded():return
            try:
                data=self.read_json();self.send_json(CATALOG.library(data.get('episode_id')).session(data),202)
            except Exception as error:self.send_json({'error':str(error)[:500]},400)
            return
        return super().do_POST()

    def voice_scope(self,data):
        if not set(data.get('episode_ids',[]))<=set(CATALOG.entries):raise ValueError('Choose existing podcasts for this permission')
        if not set(data.get('advertiser_ids',[]))<=set(LIBRARY.by_ad):raise ValueError('Choose known permitted advertisers')

def main():
    global LIBRARY,CATALOG,VOICES,DELIVERY
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=int(setting('PORT','5097')));args=parser.parse_args();LIBRARY=Library();VOICES=VoiceLibrary(LIBRARY.root/'voices');VOICES.api_lock=LIBRARY.api_lock;CATALOG=PodcastCatalog(LIBRARY,VOICES)
    DELIVERY=ListenerDelivery()
    http=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);print(f'Live podcast demo: http://127.0.0.1:{args.port}',flush=True)
    try:http.serve_forever()
    except KeyboardInterrupt:http.server_close()
if __name__=='__main__':main()
