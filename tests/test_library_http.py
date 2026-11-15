import io,json,sys,tempfile,threading,unittest,urllib.request,urllib.error,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live_cache import Library
from voice_library import VoiceLibrary
from podcast_catalog import PodcastCatalog
from test_voice_library import tone
import live_server,server

class LibraryHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name);source=root/'source.wav';source.write_bytes(tone(1))
        base=Library.__new__(Library);base.root=root/'cache';base.root.mkdir();base.source=source;base.duration=1;base.episode_id='a'*24;base.chunk_set_id='b'*16;base.ads=[];base.by_ad={'brand_a':{'id':'brand_a'}};base.custom={};base.custom_path=base.root/'custom.json';base.prompt='fixture';base.prompt_hash='fixture';base.api_lock=threading.RLock();base.render_lock=threading.Lock();base.sessions={}
        self.old=(live_server.LIBRARY,live_server.CATALOG,live_server.VOICES);self.voices=VoiceLibrary(base.root/'voices');self.catalog=PodcastCatalog(base,self.voices);live_server.LIBRARY=base;live_server.CATALOG=self.catalog;live_server.VOICES=self.voices
        self.http=live_server.ThreadingHTTPServer(('127.0.0.1',0),live_server.Handler);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.http.server_port)
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();live_server.LIBRARY,live_server.CATALOG,live_server.VOICES=self.old;self.temp.cleanup()
    def post(self,path,data,headers=None):
        headers={'X-App-Token':server.TOKEN,**(headers or {})};body=data if isinstance(data,bytes) else json.dumps(data).encode();headers.setdefault('Content-Type','application/json');return json.load(urllib.request.urlopen(urllib.request.Request(self.url+path,data=body,headers=headers)))
    def voice(self):
        metadata={'name':'Synthetic test','speaker':'Not a person','authorized_by':'Test fixture','owner_type':'brand','rights_confirmed':True,'episode_ids':['a'*24],'advertiser_ids':['brand_a']}
        from urllib.parse import quote
        return self.post('/api/voices/upload',tone(6),{'X-Filename':'sample.wav','X-Voice-Metadata':quote(json.dumps(metadata))})
    def test_podcast_upload_and_dedupe_http(self):
        a=self.post('/api/podcasts/upload',tone(2),{'X-Filename':'demo.wav'});b=self.post('/api/podcasts/upload',tone(2),{'X-Filename':'renamed.wav'});self.assertEqual(a['id'],b['id']);self.assertTrue(b['upload_cache_hit'])
    def test_voice_upload_requires_rights_and_hides_embedding_paths(self):
        from urllib.parse import quote
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/voices/upload',tone(6),{'X-Filename':'sample.wav','X-Voice-Metadata':quote(json.dumps({'rights_confirmed':False,'episode_ids':[],'advertiser_ids':[]}))})
        item=self.voice();self.assertEqual(item['status'],'sample_uploaded');self.assertNotIn('reference_path',item)
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/voices/'+item['id']+'/activate',{'send_to_gnani':False})
    def test_revocation_blocks_cached_voice_media_and_direct_route(self):
        item=self.voice();vid=item['id'];self.voices.items[vid]['status']='ready';asset='d'*64;media=live_server.LIBRARY.root/'media';media.mkdir();(media/(asset+'.wav')).write_bytes(tone(.2));self.voices.protect(asset,vid,'a'*24,'brand_a')
        sid='e'*16;live_server.LIBRARY.sessions[sid]={'slots':[{'asset_key':asset,'clone_voice_id':vid,'advertiser_id':'brand_a'}]}
        url=self.url+'/api/live/voice-media/'+sid+'/'+asset+'.wav'
        response=urllib.request.urlopen(url);self.assertEqual(response.headers['Cache-Control'],'no-store');self.assertTrue(response.read().startswith(b'RIFF'))
        self.post('/api/voices/'+vid+'/revoke',{})
        for target in [url,self.url+'/api/live/media/'+asset+'.wav']:
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(target)
            self.assertEqual(error.exception.code,403)

if __name__=='__main__':unittest.main()
