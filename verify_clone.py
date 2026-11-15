"""Credential-free smoke of empty startup, upload and audio streaming."""
import array,io,json,os,re,socket,subprocess,sys,tempfile,time,urllib.request,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    with tempfile.TemporaryDirectory() as folder:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=dict(os.environ,INTERVALS_DATA_DIR=str(Path(folder)/'data'))
        process=subprocess.Popen([sys.executable,str(ROOT/'live_server.py'),'--port',str(port)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        try:
            base='http://127.0.0.1:'+str(port)
            for _ in range(100):
                try:page=urllib.request.urlopen(base,timeout=1).read().decode();break
                except OSError:
                    if process.poll() is not None:raise RuntimeError(process.stderr.read())
                    time.sleep(.1)
            else:raise RuntimeError('Server did not start')
            assert 'studio-layout.js' in urllib.request.urlopen(base+'/studio').read().decode()
            assert 'advertiserJson' not in page
            assert json.load(urllib.request.urlopen(base+'/api/listen/library'))['episodes']==[]
            assert json.load(urllib.request.urlopen(base+'/api/podcasts'))==[]
            token=re.search('name="app-token" content="([^"]+)',page).group(1)
            audio=io.BytesIO()
            with wave.open(audio,'wb') as wav:wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(array.array('h',[1000,-1000]*16000).tobytes())
            request=urllib.request.Request(base+'/api/podcasts/upload',data=audio.getvalue(),headers={'X-App-Token':token,'X-Filename':'clone-smoke.wav','Content-Type':'application/octet-stream'})
            episode=json.load(urllib.request.urlopen(request));assert episode['status']=='uploaded'
            listening=json.load(urllib.request.urlopen(base+'/api/listen/library'));assert len(listening['episodes'])==1
            request=urllib.request.Request(base+listening['episodes'][0]['audio_url'],headers={'Range':'bytes=0-31'})
            response=urllib.request.urlopen(request);assert response.status==206 and len(response.read())==32
            print('PASS: clean startup, listener/studio, empty catalog, first upload, range streaming; no external APIs')
        finally:
            process.terminate()
            try:process.communicate(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.communicate()
if __name__=='__main__':main()
