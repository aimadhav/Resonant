import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import live_cache as live

class RepairTests(unittest.TestCase):
    def run_draft(self,checks):
        lib=live.Library.__new__(live.Library);lib.prompt='test';lib.metrics={'provider_calls':0}
        case={'earlier_relevant_passages':[]};slot={'id':'slot'}
        with tempfile.TemporaryDirectory() as folder, patch.object(live.writer,'Generator') as factory, patch.object(live.writer,'check_output',side_effect=checks):
            factory.return_value.attempt_count=1
            factory.return_value.generate.return_value=([{'scenario_id':'slot'}],{})
            before=live.writer.SYSTEM
            result=lib.draft_checked({},slot,case,{},Path(folder))
            self.assertEqual(live.writer.SYSTEM,before)
            return result,factory.return_value.generate.call_count,lib.metrics['provider_calls']

    def test_invalid_citation_gets_one_repair(self):
        result,calls,metrics=self.run_draft([{'violations':['Earlier stance citation is unknown']},{'violations':[]}])
        self.assertTrue(result[1]['passed']);self.assertEqual((calls,metrics),(2,2))

    def test_repeated_invalid_citation_stays_blocked(self):
        result,calls,_=self.run_draft([{'violations':['Earlier stance citation is unknown']}]*2)
        self.assertFalse(result[1]['passed']);self.assertEqual(calls,2)

    def test_valid_draft_does_not_retry(self):
        result,calls,_=self.run_draft([{'violations':[]}])
        self.assertTrue(result[1]['passed']);self.assertEqual(calls,1)

    def test_empty_earlier_context_requires_empty_evidence(self):
        text=live.citation_instructions({'earlier_relevant_passages':[]})
        self.assertIn('stance_evidence MUST be []',text)
        self.assertIn('Allowed earlier chunk IDs: []',text)

if __name__=='__main__':unittest.main()
