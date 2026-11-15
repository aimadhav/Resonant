"""Launch local GPU/CPU processing in an isolated optional environment."""
import json,os,subprocess,time,threading
from pathlib import Path
from kaggle_job import Job,ROOT
from settings import setting
LOCAL_PROCESSING_LOCK=threading.Lock()

def processor_python():
    explicit=setting('LOCAL_PROCESSOR_PYTHON')
    return Path(explicit).expanduser().resolve() if explicit else ROOT/'.processor-venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def check_runtime(device='auto'):
    python=processor_python()
    if not python.is_file():raise ValueError('Local processing is not installed. Run python setup.py --processing, then restart the app.')
    result=subprocess.run([str(python),str(ROOT/'local_processor.py'),'--check','--device',device],capture_output=True,text=True,timeout=60)
    if result.returncode:raise ValueError((result.stderr or 'Local runtime check failed')[-1600:])
    return json.loads(result.stdout.strip().splitlines()[-1])

class LocalJob(Job):
    def run(self):
        self.update(status='running',stage='local_queue',message='Waiting for the local processing slot')
        with LOCAL_PROCESSING_LOCK:self._execute()
    def _execute(self):
        started=time.perf_counter();out=self.directory/'result';out.mkdir(exist_ok=True)
        try:
            self.update(status='running',stage='local_processing',message='Processing on your device, model downloads may be needed on the first run')
            args=[str(processor_python()),str(ROOT/'local_processor.py'),'--audio',str(self.directory/'input'/self.metadata['audio_file']),'--out',str(out),'--device',self.metadata.get('device','auto'),'--model',self.metadata['asr_model']]
            with (out/'worker.log').open('w',encoding='utf-8') as log:
                result=subprocess.run(args,stdout=log,stderr=log,text=True,timeout=24*3600)
            status=json.loads((out/'worker_status.json').read_text()) if (out/'worker_status.json').exists() else {}
            if result.returncode or status.get('status')!='complete':raise RuntimeError(status.get('error','Local worker failed, inspect worker.log'))
            self.update(status='complete',stage='complete',message='Local processing complete, results saved on this device',result_path=str(out),elapsed_seconds=round(time.perf_counter()-started,6))
        except Exception as error:self.update(status='failed',stage='failed',message=str(error),elapsed_seconds=round(time.perf_counter()-started,6))
