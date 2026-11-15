import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnani_tts_ads import spoken_text,prepare_audio_tags
from creative_ad_simulation import PROMPT

class SpokenCopyTests(unittest.TestCase):
    def test_codes_are_speakable_without_changing_source(self):
        source='Use code MYWEEK or FIRSTCUP'
        self.assertEqual(spoken_text(source),'Use code My week or First cup')
        self.assertEqual(source,'Use code MYWEEK or FIRSTCUP')

    def test_no_guessing_or_partial_token_replacement(self):
        self.assertEqual(spoken_text('MYWEEKEND NASA ABC123'),'MYWEEKEND NASA ABC123')

    def test_explicit_pronunciation_controls_ambiguous_code(self):
        self.assertEqual(spoken_text('Use AB12',{'AB12':'A B one two'}),'Use A B one two')

    def test_writer_loads_generalizable_spoken_copy_rules(self):
        self.assertIn('Spoken-copy pass',PROMPT)
        self.assertIn('keep the exact',PROMPT.lower())
        self.assertIn('never increase speed above 1.0',PROMPT)

    def test_pause_reaches_tts_and_code_stays_speakable(self):
        self.assertEqual(spoken_text('Your next week, <pauses> use MYWEEK'),'Your next week, <pauses> use My week')

    def test_invalid_tags_do_not_silently_pass(self):
        for text in ['Hello <pause> there','Hello <Pauses> there','Hello </pauses> there','Hello <pauses time="1s"> there','Hello <pauses there']:
            with self.subTest(text=text),self.assertRaises(ValueError):prepare_audio_tags(text)

    def test_stacked_and_edge_pauses_rejected(self):
        for text in ['<pauses> hello','hello <pauses>','hello <pauses> <pauses> there']:
            with self.subTest(text=text),self.assertRaises(ValueError):prepare_audio_tags(text)

    def test_tags_are_not_counted_as_spoken_words(self):
        from ad_simulation import words
        self.assertEqual(words('Choose tomorrow <pauses> write three priorities'),['choose','tomorrow','write','three','priorities'])

if __name__=='__main__':unittest.main()
