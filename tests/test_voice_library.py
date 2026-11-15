import io,json,math,shutil,sys,tempfile,threading,unittest,wave
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voice_library import VoiceLibrary

def tone(seconds,rate=24000):
    import array
    out=io.BytesIO();samples=array.array('h',[int(1000*math.sin(i*.1)) for i in range(round(seconds*rate))])
    with wave.open(out,'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(samples.tobytes())
    return out.getvalue()

@unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg required')
class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.registry=VoiceLibrary(self.root/'voices');self.sample=self.root/'sample.wav';self.sample.write_bytes(tone(6));self.meta={'name':'Synthetic test signal','speaker':'Synthetic tone, not a person','owner_type':'host','authorized_by':'Test fixture','episode_ids':['episode-a'],'advertiser_ids':['brand-a'],'rights_confirmed':True}
    def tearDown(self):self.temp.cleanup()
    def add(self):return self.registry.add(self.meta,self.sample)['id']
    def ready(self,vid):
        payload={'success':True,'data':{'voice_clone_embedding':{'embedding':'test-only','shape':[1,768],'dtype':'torch.bfloat16'}}}
        with patch('voice_library.load_env',return_value={'GNANI_API_KEY':'fixture-key'}),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):self.registry.embed(vid)
    def test_permission_required(self):
        self.meta['rights_confirmed']=False
        with self.assertRaises(ValueError):self.add()
        self.assertFalse(self.registry.items)
    def test_sample_duration_enforced(self):
        self.sample.write_bytes(tone(1))
        with self.assertRaises(ValueError):self.add()
    def test_scope_and_revocation_enforced(self):
        vid=self.add();self.ready(vid);self.registry.authorize(vid,'episode-a','brand-a')
        for episode,brand in [('episode-b','brand-a'),('episode-a','brand-b')]:
            with self.assertRaises(PermissionError):self.registry.authorize(vid,episode,brand)
        self.registry.protect('asset',vid,'episode-a','brand-a');self.registry.revoke(vid)
        with self.assertRaises(PermissionError):self.registry.allow_asset('asset','episode-a','brand-a')
    def test_embedding_status_changes_permission_cache_epoch(self):
        vid=self.add();epoch=self.registry.epoch();self.ready(vid);self.assertNotEqual(epoch,self.registry.epoch())
        public=self.registry.public()[0];self.assertNotIn('embedding_path',public);self.assertNotIn('reference_path',public)
    def test_regrant_replaces_scope_instead_of_expanding_silently(self):
        vid=self.add();self.ready(vid);self.registry.grant(vid,dict(self.meta,episode_ids=['episode-b']))
        with self.assertRaises(PermissionError):self.registry.authorize(vid,'episode-a','brand-a')
        self.registry.authorize(vid,'episode-b','brand-a');self.assertEqual(len(self.registry.items[vid]['history']),2)
    def test_clone_request_contract_and_local_pause_tempo(self):
        vid=self.add();self.ready(vid);requests=[]
        def provider(request,**kwargs):requests.append(json.loads(request.data));return io.BytesIO(tone(.25,44100))
        out=self.root/'clone.wav'
        with patch('voice_library.load_env',return_value={'GNANI_API_KEY':'fixture-key'}),patch('urllib.request.urlopen',side_effect=provider):info=self.registry.synthesize(vid,'episode-a','brand-a','One beat <pauses> second beat',.85,out)
        self.assertEqual(len(requests),2);self.assertTrue(all(r['model']=='vachana-vc-v1' and '<pauses>' not in r['text'] for r in requests));self.assertEqual(info['provider_calls'],2)
        with wave.open(str(out),'rb') as wav:self.assertEqual(wav.getframerate(),48000);self.assertGreater(wav.getnframes()/48000,.8)
        self.registry.revoke(vid)
        with self.assertRaises(PermissionError):self.registry.synthesize(vid,'episode-a','brand-a','One beat',1,out)

if __name__=='__main__':unittest.main()
