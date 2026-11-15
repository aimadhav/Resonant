import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contextual_selection import preceding_window

class WindowTests(unittest.TestCase):
    def test_last_200_words_only_before_cut(self):
        sentences=[{'id':str(i),'start':i,'end':i+1,'text':' '.join([str(i)]*30)} for i in range(15)]
        slot={'cut_time':10,'context':{'before_context':sentences[:2],'after_context':[sentences[11]]}}
        result=preceding_window(slot,sentences,[])
        text=' '.join(s['text'] for s in result['before_context'])
        self.assertEqual(len(text.split()),200)
        self.assertEqual(result['before_context'][-1]['id'],'9')
        self.assertTrue(all(s['end']<=10 for s in result['before_context']))
        self.assertEqual(len(slot['context']['before_context']),2)
    def test_short_opening_is_not_padded_or_fabricated(self):
        slot={'cut_time':2,'context':{'before_context':[{'id':'a','start':0,'end':1,'text':'A short opening'}]}}
        self.assertEqual(preceding_window(slot,[],[])['before_context'][0]['text'],'A short opening')

if __name__=='__main__':unittest.main()
