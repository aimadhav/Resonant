import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live_cache import Library

class ReviewRepairTests(unittest.TestCase):
    def test_invalid_quote_retries_same_packet(self):
        lib=Library.__new__(Library);lib.metrics={'provider_calls':0};client=Mock();client.events=[];packet={'script':'unchanged'}
        client.call.return_value=([{'evidence':[]}],{})
        with tempfile.TemporaryDirectory() as folder,patch('ad_simulation_review.validate_quality',side_effect=[ValueError('Review evidence is not an exact source excerpt'),{'decision':'pass'}]):
            result,_=lib.review_checked(client,packet,{},'review prompt',Path(folder))
        self.assertEqual(result['decision'],'pass');self.assertEqual(client.call.call_count,2)
        self.assertEqual(client.call.call_args_list[0].args[0],client.call.call_args_list[1].args[0])
    def test_repeated_invalid_quotes_remain_blocked(self):
        lib=Library.__new__(Library);lib.metrics={'provider_calls':0};client=Mock();client.events=[];client.call.return_value=([{}],{})
        with tempfile.TemporaryDirectory() as folder,patch('ad_simulation_review.validate_quality',side_effect=ValueError('Bad quote')):
            with self.assertRaisesRegex(RuntimeError,'after two attempts'):lib.review_checked(client,{}, {},'prompt',Path(folder))
        self.assertEqual(client.call.call_count,2)

if __name__=='__main__':unittest.main()
