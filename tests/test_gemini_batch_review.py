import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gemini_batch_review import Reviewer,verify


class BatchReviewTests(unittest.TestCase):
    def test_model_and_key_failover_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'.env'
            path.write_text('GEMINI_API_KEY=primary-test\nGEMINI_BACKUP_API_KEY=backup-test\nGEMINI_MODEL=gemini-3.5-flash-lite\nGEMINI_BACKUP_MODEL=gemini-3.1-flash-lite\n')
            reviewer=Reviewer(path,Path(tmp))
            self.assertEqual([(m,label) for m,label,key in reviewer.routes()],
                [('gemini-3.5-flash-lite','primary'),('gemini-3.5-flash-lite','backup'),
                 ('gemini-3.1-flash-lite','primary'),('gemini-3.1-flash-lite','backup')])

    def test_duplicate_key_is_not_retried_as_another_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'.env';path.write_text('GEMINI_API_KEY=same-test\nGEMINI_BACKUP_API_KEY=same-test\n')
            self.assertEqual(len(Reviewer(path,Path(tmp)).routes()),2)

    def test_unique_exact_quote_can_repair_sentence_id(self):
        packet={'slot_id':'s1','before_context':[{'id':'t1','text':'The explanation is finished.'}],
                'after_context':[{'id':'t2','text':'A separate subject starts now.'}]}
        raw={'slot_id':'s1','decision':'accept','thought_complete':True,'pending_answer_example_or_payoff':False,
             'resume_clear':True,'reason':'The unit is complete.','evidence':[{'sentence_id':'t2','quote':'The explanation is finished.'}]}
        result=verify(raw,packet)
        self.assertEqual(result['evidence'][0]['sentence_id'],'t1')
        self.assertEqual(len(result['citation_id_repairs']),1)

    def test_unfounded_quote_still_fails(self):
        packet={'slot_id':'s1','before_context':[{'id':'t1','text':'A real sentence.'}],'after_context':[]}
        raw={'slot_id':'s1','decision':'reject','thought_complete':False,'pending_answer_example_or_payoff':True,
             'resume_clear':False,'reason':'Incomplete.','evidence':[{'sentence_id':'t1','quote':'An invented sentence.'}]}
        with self.assertRaises(ValueError):verify(raw,packet)


if __name__=='__main__':unittest.main()
