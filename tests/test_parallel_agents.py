import sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live_cache import Library
import ad_simulation as writer
import gemini_batch_review as transport

class ParallelTests(unittest.TestCase):
    def test_long_form_beats_are_joined_for_tts(self):
        def call(client,*args):
            self.assertIn('script_beats',client.schema_override['properties']['reviews']['items']['required'])
            return [{'decision':'generate','script_beats':[' '.join(['word']*25)]*5}],{}
        with tempfile.TemporaryDirectory() as folder,patch.object(transport.Reviewer,'call',call):
            generator=writer.Generator(Path(folder)/'env',Path(folder));generator.isolated=True;generator.long_form=True
            outputs,_=generator.generate([{'scenario_id':'slot','generation_input':{}}],'slot')
        text=outputs[0]['script_text'];self.assertEqual(text.count('<pauses>'),4)
        self.assertEqual(len(text.replace('<pauses>','').split()),125)

    def test_three_slots_can_reach_strategists_concurrently(self):
        lib=Library.__new__(Library);barrier=threading.Barrier(3)
        lib.slots=[{'id':str(i)} for i in range(3)];lib.metrics={}
        result={'id':'paralleltest','slots':[{'id':str(i)} for i in range(3)]}
        def choose(*args):barrier.wait(timeout=3);return None,[],{'reason':'No natural fit'}
        with tempfile.TemporaryDirectory() as folder,patch('contextual_selection.choose',side_effect=choose):
            lib.root=Path(folder);lib._prepare(result,[],{},'Riyaa',.95,Path(folder)/'decision.json',True)
        self.assertTrue(all(s['status']=='skipped' for s in result['slots']))
        self.assertEqual(result['agent_network']['max_parallel_slots'],3)

    def test_writer_instructions_are_isolated_between_threads(self):
        barrier=threading.Barrier(2);seen=[]
        def call(client,*args):barrier.wait(timeout=3);seen.append(client.prompt_override);return [],{}
        with tempfile.TemporaryDirectory() as folder,patch.object(transport.Reviewer,'call',call):
            def run(label):
                generator=writer.Generator(Path(folder)/'env',Path(folder));generator.isolated=True;generator.instructions=label
                generator.generate([{'scenario_id':label,'generation_input':{}}],label)
            threads=[threading.Thread(target=run,args=(label,)) for label in ('alpha','beta')]
            for t in threads:t.start()
            for t in threads:t.join()
        self.assertEqual(len(seen),2)
        self.assertTrue(any(p.startswith('alpha\n') for p in seen));self.assertTrue(any(p.startswith('beta\n') for p in seen))

if __name__=='__main__':unittest.main()
