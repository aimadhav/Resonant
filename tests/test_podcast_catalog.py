import hashlib,io,json,shutil,sys,tempfile,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live_cache import Library
from podcast_catalog import PodcastCatalog
from voice_library import VoiceLibrary
from test_voice_library import tone

@unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg required')
class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'source.wav';self.source.write_bytes(tone(1))
        base=Library.__new__(Library);base.root=self.root/'cache';base.root.mkdir();base.source=self.source;base.duration=1;base.episode_id='a'*24;base.chunk_set_id='b'*16;base.ads=[];base.by_ad={};base.custom={};base.custom_path=base.root/'custom.json';base.prompt='fixture';base.prompt_hash='fixture';base.api_lock=threading.RLock();base.render_lock=threading.Lock()
        self.voices=VoiceLibrary(base.root/'voices');self.catalog=PodcastCatalog(base,self.voices)
    def tearDown(self):self.temp.cleanup()
    def test_upload_deduplicates_content_not_filename(self):
        data=tone(2);a=self.catalog.upload(io.BytesIO(data),len(data),'first.wav');b=self.catalog.upload(io.BytesIO(data),len(data),'renamed.wav')
        self.assertEqual(a['id'],b['id']);self.assertFalse(a['upload_cache_hit']);self.assertTrue(b['upload_cache_hit'])
    def test_prepared_original_is_recognized(self):
        data=self.source.read_bytes();item=self.catalog.upload(io.BytesIO(data),len(data),'again.wav');self.assertEqual(item['id'],'a'*24);self.assertTrue(item['upload_cache_hit'])
    def test_uploaded_podcast_plays_without_analysis_or_ad_slots(self):
        data=tone(2);item=self.catalog.upload(io.BytesIO(data),len(data),'new.wav');lib=self.catalog.library(item['id']);self.assertEqual(lib.slots,[]);self.assertAlmostEqual(lib.duration,2,places=2);self.assertIn(lib.chunk_set_id,lib.chunks[0]['url']);self.assertTrue(lib.chunk(0).exists())
    def test_cloud_analysis_requires_explicit_rights(self):
        data=tone(2);item=self.catalog.upload(io.BytesIO(data),len(data),'new.wav')
        with self.assertRaises(ValueError):self.catalog.analyze(item['id'],False)
        self.assertEqual(self.catalog.entries[item['id']]['status'],'uploaded')
    def test_invalid_audio_is_rejected(self):
        with self.assertRaises(ValueError):self.catalog.upload(io.BytesIO(b'not audio'),9,'bad.wav')

if __name__=='__main__':unittest.main()
