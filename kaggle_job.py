"""Local orchestration only: transfers, scheduling, status, and artifact retrieval."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parent
CLI = [sys.executable, '-c', 'from kaggle.cli import main; main()']


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def cli(args, timeout=180):
    config_dir=Path(os.environ.get('KAGGLE_CONFIG_DIR',str(ROOT/'.kaggle')))
    config_dir.mkdir(parents=True,exist_ok=True)
    temporary_dir=ROOT/'.runtime-temp'
    temporary_dir.mkdir(exist_ok=True)
    return subprocess.run(CLI + list(args), capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout,
                          env=dict(os.environ, PYTHONIOENCODING='utf-8',KAGGLE_CONFIG_DIR=str(config_dir),
                                   TEMP=str(temporary_dir),TMP=str(temporary_dir),TMPDIR=str(temporary_dir)))


def preflight():
    import importlib.util
    installed = importlib.util.find_spec('kaggle') is not None
    return {'cli_installed': installed,
            'username_default': __import__('settings').setting('KAGGLE_USERNAME'),
            'message': 'CLI installed; use Check connection to verify authentication.' if installed else
                       'Run start.ps1 to install the Kaggle CLI. MCP login and CLI login are separate.'}


def verify_auth():
    result = cli(['datasets', 'list', '--mine'],timeout=45)
    # Never return CLI stdout from authentication checks: do not expose credentials.
    return {'authenticated': result.returncode == 0,
            'message': 'Kaggle CLI authenticated.' if result.returncode == 0 else
            'Kaggle CLI authentication failed. Run ./login.ps1 in the app folder, or configure KAGGLE_API_TOKEN. MCP authentication does not automatically authenticate this local app.'}


def kernel_source(dataset_slug):
    # A pushed script is self-contained: sibling source files are not pushed by kernels push.
    processor = (ROOT/'pipeline.py').read_text(encoding='utf-8')
    requirements = [line for line in (ROOT/'requirements-kaggle.txt').read_text().splitlines() if line and not line.startswith('#')]
    return f'''import os, sys, json, time, traceback, subprocess, shutil
from pathlib import Path
started = time.perf_counter()
out = Path('/kaggle/working/result')
out.mkdir(parents=True, exist_ok=True)
setup_start = time.perf_counter()
print('START dependency_setup', flush=True)
try:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '-q', *{requirements!r}], check=True)
    setup_seconds = time.perf_counter() - setup_start
    print(f'END dependency_setup: {{setup_seconds:.3f}}s', flush=True)
    source = Path('/kaggle/working/pipeline.py')
    source.write_text({processor!r}, encoding='utf-8')
    sys.path.insert(0, '/kaggle/working')
    from pipeline import process, Timings, write_json
    timing = Timings(out)
    timing.started = started
    timing.rows.append({{'stage':'dependency_setup','seconds':round(setup_seconds,6),'status':'complete'}})
    with timing.stage('worker_initialization'):
        inputs = list(Path('/kaggle/input').rglob('job-input.json'))
        if len(inputs) != 1:
            raise RuntimeError('Expected exactly one job-input.json in attached private dataset')
        directory = inputs[0].parent
        job = json.loads(inputs[0].read_text())
        cfg = json.loads((directory/'config.json').read_text())
    transcript = directory/'transcript.json'
    process(directory/job['audio_file'], transcript if transcript.exists() else None, out, cfg, timing)
    write_json(out/'worker_status.json',{{'status':'complete'}})
except BaseException as error:
    (out/'worker_status.json').write_text(json.dumps({{'status':'failed','error':str(error)}}))
    (out/'error.log').write_text(traceback.format_exc())
    if 'timing' in globals():
        timing.save()
    else:
        (out/'compute_timings.json').write_text(json.dumps({{'total_seconds':time.perf_counter()-started,'stages':[{{'stage':'dependency_setup','seconds':time.perf_counter()-setup_start,'status':'failed'}}]}}))
    traceback.print_exc()
finally:
    shutil.make_archive('/kaggle/working/package', 'zip', out)
'''


class Job:
    def __init__(self, directory, metadata):
        self.directory = Path(directory)
        self.metadata = metadata
        self.lock = threading.RLock()
        self.thread = None
        self.state = {'id': self.directory.name, 'status':'awaiting_upload', 'stage':'awaiting_upload',
                      'message':'Choose audio to start.', 'events':[], 'timings':[], **metadata}
        self.save()

    def save(self):
        with self.lock:
            temp=self.directory/'state.tmp'
            dump(temp,self.state)
            temp.replace(self.directory/'state.json')

    def update(self, **values):
        with self.lock:
            self.state.update(values)
            if 'message' in values:
                self.state['events'].append({'time':time.time(),'stage':self.state['stage'],'message':values['message']})
            self.save()

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def command(self, stage, args, timeout=1800):
        self.update(stage=stage,message=stage.replace('_',' ').capitalize())
        begin=time.perf_counter()
        try:
            result=cli(args,timeout)
        except subprocess.TimeoutExpired:
            elapsed=time.perf_counter()-begin
            self.state['timings'].append({'stage':stage,'seconds':round(elapsed,6),'status':'timeout'})
            self.save()
            raise TimeoutError(f'{stage} exceeded its {timeout}s timeout; a remote operation may still be running')
        elapsed=time.perf_counter()-begin
        # CLI command logs contain only non-secret transfer/status output.
        with (self.directory/'orchestration.log').open('a',encoding='utf-8') as f:
            f.write(f'\n{stage}: {elapsed:.6f} s, exit={result.returncode}\n')
            f.write(result.stdout+'\n'+result.stderr+'\n')
        self.state['timings'].append({'stage':stage,'seconds':round(elapsed,6),'status':'complete' if result.returncode==0 else 'failed'})
        self.save()
        if result.returncode:
            raise RuntimeError(f'{stage} failed. Check orchestration.log and your Kaggle account. '+
                               (result.stderr or result.stdout)[-600:])
        return result.stdout

    def run(self):
        begin=time.perf_counter()
        try:
            if not preflight()['cli_installed']:raise RuntimeError('Kaggle CLI is optional and not installed. Run python setup.py --kaggle, then authenticate your own account.')
            self.update(status='running',started_at=time.time())
            auth_start=time.perf_counter()
            authenticated=verify_auth()['authenticated']
            self.state['timings'].append({'stage':'authentication_check','seconds':round(time.perf_counter()-auth_start,6),
                                         'status':'complete' if authenticated else 'failed'})
            if not authenticated:
                raise RuntimeError('Kaggle CLI is not authenticated. Run ./login.ps1 in the app folder. The app cannot use the Codex MCP login.')
            dataset_slug='podcast-input-'+self.directory.name
            kernel_slug='podcast-slots-'+self.directory.name
            username=self.metadata['username']
            dataset_ref=f'{username}/{dataset_slug}'
            kernel_ref=f'{username}/{kernel_slug}'
            self.update(dataset_ref=dataset_ref,kernel_ref=kernel_ref)
            inputs=self.directory/'input'
            dump(inputs/'dataset-metadata.json',{'title':'Podcast input '+self.directory.name,
                'id':dataset_ref,'licenses':[{'name':'other'}]})
            dump(inputs/'job-input.json',{'audio_file':self.metadata['audio_file']})
            cfg=json.loads((ROOT/'config.json').read_text())
            cfg['asr_model']=self.metadata['asr_model']
            dump(inputs/'config.json',cfg)
            self.command('dataset_upload',['datasets','create','-p',str(inputs),'-t'],3600)
            self.update(stage='dataset_ready',message='Waiting for the private input dataset to become ready.')
            ready_start=time.perf_counter()
            while time.perf_counter()-ready_start<600:
                response=cli(['datasets','status',dataset_ref],timeout=60)
                text=(response.stdout+response.stderr).lower()
                if response.returncode==0 and re.search(r'\bready\b',text):
                    break
                if re.search(r'\b(error|failed)\b',text) and response.returncode==0:
                    raise RuntimeError('Kaggle dataset processing failed')
                time.sleep(10)
            else:
                raise TimeoutError('Private input dataset was not ready within 10 minutes')
            self.state['timings'].append({'stage':'dataset_readiness_wait','seconds':round(time.perf_counter()-ready_start,6),'status':'complete'})
            kernel=self.directory/'kernel';kernel.mkdir(exist_ok=True)
            (kernel/'run.py').write_text(kernel_source(dataset_slug),encoding='utf-8')
            dump(kernel/'kernel-metadata.json',{'id':kernel_ref,'title':'Podcast slots '+self.directory.name,
                'code_file':'run.py','language':'python','kernel_type':'script',
                'is_private':True,'enable_gpu':True,'enable_internet':True,
                'dataset_sources':[dataset_ref],'competition_sources':[],'kernel_sources':[]})
            self.command('kernel_submit',['kernels','push','-p',str(kernel)],300)
            self.update(stage='kaggle_run',message='Kaggle job submitted. Waiting for compute; open the notebook for live worker logs.',
                        kernel_url='https://www.kaggle.com/code/'+kernel_ref)
            wait_start=time.perf_counter()
            status_failures=0
            while time.perf_counter()-wait_start<4*3600:
                response=cli(['kernels','status',kernel_ref],timeout=60)
                text=(response.stdout+response.stderr).lower()
                if response.returncode:
                    status_failures+=1
                    if status_failures>=5:
                        raise RuntimeError('Could not read Kaggle run status after five retries. The remote job may still be running: https://www.kaggle.com/code/'+kernel_ref)
                    self.update(message=f'Kaggle status request failed; retrying ({status_failures}/5). The remote job is not cancelled.')
                    time.sleep(15)
                    continue
                status_failures=0
                if re.search(r'\bcomplete\b',text):
                    break
                if re.search(r'\b(error|failed|cancelled|canceled)\b',text):
                    raise RuntimeError('Kaggle notebook failed or was cancelled. Inspect its logs: https://www.kaggle.com/code/'+kernel_ref)
                time.sleep(15)
            else:
                raise TimeoutError('Stopped waiting after four hours; the Kaggle notebook may still be running')
            self.state['timings'].append({'stage':'kaggle_queue_and_run_wait','seconds':round(time.perf_counter()-wait_start,6),'status':'complete'})
            downloaded=self.directory/'download';downloaded.mkdir(exist_ok=True)
            self.command('output_download',['kernels','output',kernel_ref,'-p',str(downloaded),'--file-pattern',r'^package\.zip$'],1800)
            archive=downloaded/'package.zip'
            if not archive.exists():
                matches=list(downloaded.rglob('package.zip'))
                if len(matches)!=1: raise RuntimeError('Kaggle did not produce package.zip')
                archive=matches[0]
            output=self.directory/'result';output.mkdir(exist_ok=True)
            with zipfile.ZipFile(archive) as z:
                for item in z.infolist():
                    destination=(output/item.filename).resolve()
                    if not destination.is_relative_to(output.resolve()):
                        raise ValueError('Unsafe path in returned artifact')
                z.extractall(output)
            worker=json.loads((output/'worker_status.json').read_text())
            if worker['status']!='complete':
                raise RuntimeError('Kaggle processing failed: '+worker.get('error','See error.log'))
            self.update(stage='packaging',message='Downloaded outputs. Adding local transfer and total timing logs.')
            self.finish_logs(begin,output)
            self.update(status='complete',stage='complete',message='Processing complete. Results are saved locally.',
                        completed_at=time.time(),result_path=str(output))
        except Exception as error:
            output=self.directory/'result';output.mkdir(exist_ok=True)
            (output/'local_error.log').write_text(traceback.format_exc(),encoding='utf-8')
            self.finish_logs(begin,output)
            self.update(status='failed',stage='failed',message=str(error),completed_at=time.time())

    def finish_logs(self,begin,output):
        import shutil
        log=self.directory/'orchestration.log'
        if log.exists(): shutil.copyfile(log,output/'orchestration.log')
        package_begin=time.perf_counter()
        archive=self.directory/'results.zip'
        # Add final timing files AFTER measuring the expensive archive build.
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for path in output.rglob('*'):
                if path.is_file() and path.name not in {'timings.json','timing.log'}:
                    z.write(path,path.relative_to(output))
        self.state['timings'].append({'stage':'local_packaging','seconds':round(time.perf_counter()-package_begin,6),'status':'complete'})
        summary={'scope':'Local orchestration; Kaggle queue and compute are combined in the wait stage.',
                 'end_to_end_after_submission_s':round(time.perf_counter()-begin,6),
                 'browser_upload_s':self.state.get('browser_upload_s'),
                 'stages':self.state['timings']}
        summary['total_elapsed_s']=round(summary['end_to_end_after_submission_s']+(summary['browser_upload_s'] or 0),6)
        compute=output/'compute_timings.json'
        if compute.exists(): summary['kaggle_compute']=json.loads(compute.read_text())
        dump(output/'timings.json',summary)
        lines=[f"Total elapsed including browser upload: {summary['total_elapsed_s']:.3f} s",
               f"End-to-end after submission: {summary['end_to_end_after_submission_s']:.3f} s",
               f"Browser-to-local upload: {summary['browser_upload_s']} s",
               'Local stages (wait includes Kaggle scheduler queue and worker execution):']
        lines += [f"  {r['stage']}: {r['seconds']:.3f} s [{r['status']}]" for r in summary['stages']]
        if 'kaggle_compute' in summary:
            lines += ['Kaggle worker stages:']+[f"  {r['stage']}: {r['seconds']:.3f} s [{r['status']}]" for r in summary['kaggle_compute']['stages']]
            lines += [f"Worker total: {summary['kaggle_compute']['total_seconds']:.3f} s"]
        (output/'timing.log').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        with zipfile.ZipFile(archive,'a',zipfile.ZIP_DEFLATED) as z:
            for name in ['timings.json','timing.log']:
                z.write(output/name,name)
