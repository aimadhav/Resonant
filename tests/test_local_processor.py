import json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import local_processor
from gemini_review import write_json

class LocalProcessorTests(unittest.TestCase):
    def test_cpu_and_cuda_selection(self):
        torch=types.SimpleNamespace(__version__='test',cuda=types.SimpleNamespace(is_available=lambda:True,get_device_name=lambda i:'Test CUDA device'))
        with patch.object(local_processor.importlib.util,'find_spec',return_value=True),patch.dict(sys.modules,torch=torch):
            self.assertEqual(local_processor.runtime('auto')['device'],'cuda')
            self.assertEqual(local_processor.runtime('cpu')['device'],'cpu')
    def test_explicit_cuda_does_not_silently_run_on_cpu(self):
        torch=types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda:False))
        with patch.object(local_processor.importlib.util,'find_spec',return_value=True),patch.dict(sys.modules,torch=torch):
            with self.assertRaisesRegex(RuntimeError,'CUDA was requested'):local_processor.runtime('cuda')
    def test_worker_calls_same_pipeline_and_writes_status(self):
        import contextlib
        class Timing:
            def __init__(self,*args,**kwargs):pass
            def stage(self,name):return contextlib.nullcontext()
            def save(self):pass
        calls=[]
        module=types.SimpleNamespace(Timings=Timing,write_json=write_json,process=lambda *args:calls.append(args))
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,pipeline=module),patch.object(local_processor,'runtime',return_value={'device':'cuda'}):
            root=Path(folder);write_json(root/'config.json',{})
            local_processor.run(root/'audio.wav',root/'out',root/'config.json',device='cuda',model='medium')
            self.assertEqual(calls[0][3]['device'],'cuda');self.assertEqual(calls[0][3]['asr_model'],'medium')
            self.assertEqual(json.loads((root/'out/worker_status.json').read_text())['status'],'complete')

if __name__=='__main__':unittest.main()
