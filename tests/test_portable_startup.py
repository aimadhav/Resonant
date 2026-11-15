import io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live_cache import Library
from podcast_catalog import PodcastCatalog
from voice_library import VoiceLibrary
from test_voice_library import tone

class PortableTests(unittest.TestCase):
    def test_empty_checkout_and_first_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Library(cache=Path(folder)/'cache');catalog=PodcastCatalog(base,VoiceLibrary(base.root/'voices'))
            self.assertEqual(catalog.public(),[]);self.assertEqual(catalog.library().duration,0)
            self.assertGreaterEqual(len(base.ads),30)
            data=tone(2);episode=catalog.upload(io.BytesIO(data),len(data),'first.wav')
            library=catalog.library();self.assertEqual(library.episode_id,episode['id']);self.assertEqual(library.slots,[])
            self.assertTrue(library.chunk(0).exists())
    def test_local_backend_does_not_require_kaggle_username(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Library(cache=Path(folder)/'cache');catalog=PodcastCatalog(base,VoiceLibrary(base.root/'voices'));data=tone(2);episode=catalog.upload(io.BytesIO(data),len(data),'first.wav')
            with patch('local_job.check_runtime',return_value={'device':'cuda'}),patch('podcast_catalog.threading.Thread') as thread:
                catalog.analyze(episode['id'],True,username='',backend='local',device='cuda')
            self.assertEqual(thread.call_args.kwargs['args'][-2:],('local','cuda'))
            self.assertEqual(catalog.entries[episode['id']]['processing_backend'],'local')
    def test_kaggle_requires_own_username(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Library(cache=Path(folder)/'cache');catalog=PodcastCatalog(base,VoiceLibrary(base.root/'voices'))
            with self.assertRaisesRegex(ValueError,'username'):catalog.analyze('missing',True,backend='kaggle')

if __name__=='__main__':unittest.main()
