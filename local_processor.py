"""Device-local equivalent of the Kaggle worker; no Kaggle account is used."""
import argparse,importlib.util,json,sys,traceback
from pathlib import Path

def runtime(device='auto'):
    missing=[name for name in ['numpy','torch','soundfile','silero_vad','sentence_transformers','whisperx'] if importlib.util.find_spec(name) is None]
    if missing:raise RuntimeError('Missing local processing packages: '+', '.join(missing)+'. Run python setup.py --processing first.')
    import torch
    cuda=torch.cuda.is_available()
    if device=='cuda' and not cuda:raise RuntimeError('CUDA was requested but PyTorch cannot access a CUDA GPU. Check the NVIDIA driver and PyTorch CUDA build, or choose CPU.')
    resolved='cuda' if cuda and device!='cpu' else 'cpu'
    return {'device':resolved,'cuda_available':cuda,'gpu':torch.cuda.get_device_name(0) if resolved=='cuda' else None,'torch':torch.__version__}

def run(audio,out,config,device='auto',model='small',transcript=None):
    from pipeline import process,Timings,write_json
    out=Path(out);out.mkdir(parents=True,exist_ok=True);timing=Timings(out,scope='Local device processing; excludes model dependency installation')
    try:
        with timing.stage('worker_initialization'):
            info=runtime(device);cfg=json.loads(Path(config).read_text());cfg.update(asr_model=model,device=info['device'])
            write_json(out/'runtime.json',info)
        process(Path(audio),Path(transcript) if transcript else None,out,cfg,timing)
        write_json(out/'worker_status.json',{'status':'complete','backend':'local','device':info['device']})
    except BaseException as error:
        write_json(out/'worker_status.json',{'status':'failed','error':str(error),'backend':'local'})
        (out/'error.log').write_text(traceback.format_exc(),encoding='utf-8');timing.save();raise

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--audio',type=Path);parser.add_argument('--out',type=Path);parser.add_argument('--config',type=Path,default=Path(__file__).with_name('config.json'));parser.add_argument('--device',choices=['auto','cuda','cpu'],default='auto');parser.add_argument('--model',choices=['small','medium','large-v3'],default='small');parser.add_argument('--transcript',type=Path)
    args=parser.parse_args()
    if args.check:print(json.dumps(runtime(args.device)));return
    if not args.audio or not args.out:parser.error('--audio and --out are required unless --check is used')
    run(args.audio,args.out,args.config,args.device,args.model,args.transcript)
if __name__=='__main__':
    try:main()
    except Exception as error:print(str(error),file=sys.stderr);sys.exit(1)
