import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gemini_review import select_packets,validate_review


class ReviewTests(unittest.TestCase):
    def test_full_timeline_sampling_and_no_scores(self):
        ss=[{'id':'t1','text':'A complete statement.','start':1,'end':2,'speaker':None}]
        candidates=[{'slot_id':str(t),'time':float(t),'base_score':1-t/100000,'shortlist_eligible':True,
            'prev_sentence_id':'t1','next_sentence_id':'t2','context':{'before':ss,'after':[]},'risk_flags':[]}
            for t in range(100,10400,30)]
        packets=select_packets(candidates,10505)
        self.assertEqual(len(packets),60)
        self.assertGreater(packets[-1]['cut_time'],9500)
        self.assertTrue(all('base_score' not in p and 'rank' not in p for p in packets))

    def packet(self):
        return {'slot_id':'s1','before_context':[{'id':'t1','text':'That completes the explanation.'}],
                'after_context':[{'id':'t2','text':'Let us discuss another topic.'}]}

    def review(self):
        return {'slot_id':'s1','decision':'accept','thought_complete':True,
            'pending_answer_example_or_payoff':False,'resume_clear':True,'reason':'The thought concludes.',
            'evidence':[{'sentence_id':'t1','quote':'completes the explanation'}]}

    def test_hallucinated_evidence_rejected(self):
        r=self.review();r['evidence'][0]['quote']='The sponsor is excellent'
        with self.assertRaises(ValueError):validate_review(r,self.packet())

    def test_contradictory_acceptance_is_uncertain(self):
        r=self.review();r['thought_complete']=False
        self.assertEqual(validate_review(r,self.packet())['decision'],'uncertain')

    def test_valid_acceptance(self):
        self.assertTrue(validate_review(self.review(),self.packet())['evidence_verified'])

    def test_extra_verbatim_evidence_is_preserved(self):
        r=self.review();r['evidence']*=5
        validated=validate_review(r,self.packet())
        self.assertEqual(len(validated['evidence']),4)
        self.assertEqual(len(validated['additional_verified_evidence']),1)


if __name__=='__main__':unittest.main()
