import array,json,math,sys,tempfile,unittest,wave
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from listener_delivery import ListenerDelivery
from unittest.mock import patch
from live_cache import write_json

class DeliveryTests(unittest.TestCase):
    def test_requires_complete_approved_stock_audio(self):
        with tempfile.TemporaryDirectory() as folder,patch('listener_delivery.ROOT',Path(folder)):
            delivery=ListenerDelivery();lib=SimpleNamespace(episode_id='episode')
            with self.assertRaises(ValueError):delivery.start(lib,{'status':'preparing'})
            with self.assertRaises(ValueError):delivery.start(lib,{'status':'complete','slots':[]})
            with self.assertRaises(ValueError):delivery.start(lib,{'status':'complete','slots':[{'status':'ready','clone_voice_id':'private'}]})

    def test_actual_audio_export_and_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.wav';raw=root/'tts/key/raw.wav';raw.parent.mkdir(parents=True)
            for file,seconds in [(source,2),(raw,.5)]:
                with wave.open(str(file),'wb') as wav:
                    wav.setparams((1,2,48000,0,'NONE','not compressed'))
                    wav.writeframes(array.array('h',[int(3000*math.sin(i*2*math.pi*440/48000)) for i in range(int(seconds*48000))]).tobytes())
            delivery=ListenerDelivery.__new__(ListenerDelivery);delivery.root=root/'listener';delivery.path=delivery.root/'deliveries.json';delivery.entries={'episode':{'status':'publishing'}}
            import threading
            delivery.lock=threading.Lock();out=root/'edition';out.mkdir()
            lib=SimpleNamespace(root=root,source=source,episode_id='episode',tts_key=lambda *args:'key')
            session={'id':'test','slots':[{'id':'slot','status':'ready','script':'Synthetic test audio','voice':'Riyaa','speed':.95,'cut_time':1}]}
            delivery._run(lib,session,out)
            self.assertEqual(delivery.get('episode')['status'],'ready')
            self.assertTrue(delivery.file('episode').exists())
            self.assertAlmostEqual(delivery.get('episode')['duration'],3.1,delta=.15)
            self.assertNotIn('file',delivery.public('episode'))

if __name__=='__main__':unittest.main()
