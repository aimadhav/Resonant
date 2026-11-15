"""No-Docker bootstrap: python setup.py [--processing] [--torch-index-url URL]."""
import argparse,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def interpreter(folder):return ROOT/folder/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
def command(args):subprocess.run([str(a) for a in args],cwd=ROOT,check=True)
def ensure_environment(folder,python):
    executable=interpreter(folder)
    if not executable.exists():command([python,'-m','venv',ROOT/folder])
    return executable
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--processing',action='store_true');parser.add_argument('--kaggle',action='store_true');parser.add_argument('--python',default=sys.executable,help='Python 3.11 or 3.12 executable used for environments');parser.add_argument('--torch-index-url',choices=['https://download.pytorch.org/whl/cu128','https://download.pytorch.org/whl/cpu']);parser.add_argument('--skip-install',action='store_true',help='Create environments without downloads, for packaging checks')
    args=parser.parse_args()
    if sys.version_info<(3,10):raise SystemExit('Use Python 3.11 or 3.12')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):raise SystemExit('Install FFmpeg (including ffprobe) and add it to PATH first. See README.md.')
    app=ensure_environment('.venv',args.python)
    if args.kaggle and not args.skip_install:command([app,'-m','pip','install','-r',ROOT/'requirements-kaggle-cli.txt'])
    if not (ROOT/'.env').exists():shutil.copyfile(ROOT/'.env.example',ROOT/'.env')
    if args.processing:
        processor=ensure_environment('.processor-venv',args.python)
        if not args.skip_install:
            if args.torch_index_url:command([processor,'-m','pip','install','torch==2.8.0','torchaudio==2.8.0','torchvision==0.23.0','--index-url',args.torch_index_url])
            command([processor,'-m','pip','install','-r',ROOT/'requirements-processing.txt'])
            command([processor,ROOT/'local_processor.py','--check'])
    print('Ready. Run: python run.py')
    print('Listener: http://127.0.0.1:5097/   Studio: http://127.0.0.1:5097/studio')
if __name__=='__main__':main()
