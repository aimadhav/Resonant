import array,copy,json,shutil,sys,tempfile,time,unittest,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live_cache import Library,digest,neutral_profile
import threading

class CacheTests(unittest.TestCase):
    def test_hash_is_stable_and_changes_with_brief(self):
        self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))
        self.assertNotEqual(digest({'claims':['old']}),digest({'claims':['new']}))

    def test_hate_wins_over_preference(self):
        lib=Library.__new__(Library);lib.categories={'slot':['alarm_clock']}
        ad={'id':'clock','name':'Clock','category':'alarm_clock','attributes':[]}
        p=neutral_profile();p['likes']['brands']=['clock'];p['hates']['brands']=['clock']
        chosen,excluded=lib.select({'id':'slot'},[ad],p)
        self.assertIsNone(chosen);self.assertTrue(excluded)

    def test_subscription_exclusion(self):
        lib=Library.__new__(Library);lib.categories={'slot':['meal_kit']}
        p=neutral_profile();p['hard_exclusions']['attributes']=['subscription_required']
        chosen,_=lib.select({'id':'slot'},[{'id':'kit','name':'Kit','category':'meal_kit','attributes':['food','subscription_required']}],p)
        self.assertIsNone(chosen)

    def test_creative_invalidation_on_context_and_prompt(self):
        lib=Library.__new__(Library);lib.episode_id='episode';lib.prompt_hash='p1';ad={'id':'a'};slot={'context':{'text':'one'}}
        before=lib.creative_key(ad,slot);lib.prompt_hash='p2'
        self.assertNotEqual(before,lib.creative_key(ad,slot))
        self.assertNotEqual(lib.creative_key(ad,slot),lib.creative_key(ad,{'context':{'text':'two'}}))

    def test_tts_key_changes_only_for_delivery_or_spoken_copy(self):
        lib=Library.__new__(Library)
        a=lib.tts_key('A <pauses> useful read','Riyaa',.95)
        self.assertNotEqual(a,lib.tts_key('A <pauses> useful read','Shivani',.95))
        self.assertNotEqual(a,lib.tts_key('A <pauses> useful read','Riyaa',.85))
        self.assertNotEqual(a,lib.tts_key('A useful read','Riyaa',.95))

    def test_register_updates_brief_and_invalidates_creative(self):
        with tempfile.TemporaryDirectory() as temp:
            lib=Library.__new__(Library);lib.custom={};lib.custom_path=Path(temp)/'custom.json';lib.lock=threading.RLock();lib.ads=[];lib.by_ad={};lib.episode_id='episode';lib.prompt_hash='prompt'
            brief={'id':'demo_planner','name':'Demo','product':'Planner','category':'focus_planner','approved_claims':['Undated layout']}
            first=lib.register(brief);key=lib.creative_key(first,{'context':{}})
            brief['approved_claims']=['Dated layout'];second=lib.register(brief)
            self.assertNotEqual(key,lib.creative_key(second,{'context':{}}));self.assertEqual(len(lib.ads),1)

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg required')
    def test_lazy_chunks_preserve_exact_source_samples_and_hit_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.wav';pcm=array.array('h',[i%1000 for i in range(44100*2)]).tobytes()
            with wave.open(str(source),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(44100);f.writeframes(pcm)
            lib=Library.__new__(Library);lib.source=source;lib.episode_dir=root;lib.rate=44100;lib.chunk_lock=threading.Lock();lib.metrics={'chunk_hits':0,'chunk_misses':0}
            points=[0,22222,44100];lib.chunks=[{'start':a/44100,'duration':(b-a)/44100,'start_frame':a,'end_frame':b} for a,b in zip(points,points[1:])]
            pieces=[]
            for i in range(2):
                with wave.open(str(lib.chunk(i)),'rb') as f:pieces.append(f.readframes(f.getnframes()))
            self.assertEqual(b''.join(pieces),pcm)
            lib.chunk(0);self.assertEqual(lib.metrics,{'chunk_hits':1,'chunk_misses':2})

if __name__=='__main__':unittest.main()
