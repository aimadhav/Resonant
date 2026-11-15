"""Cross-platform entry point without environment activation."""
import os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent
python=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
if not python.exists():raise SystemExit('Run python setup.py first')
if __name__=='__main__':
    try:raise SystemExit(subprocess.call([str(python),str(root/'live_server.py'),*sys.argv[1:]],cwd=root))
    except KeyboardInterrupt:pass
