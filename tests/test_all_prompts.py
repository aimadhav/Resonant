import importlib,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import all_prompts
import creative_ad_simulation
from live_cache import Library

class PromptConfigurationTests(unittest.TestCase):
    def test_central_copywriter_edit_reaches_library(self):
        original=all_prompts.COPYWRITER
        try:
            with patch.object(all_prompts,'COPYWRITER','My custom copywriting direction'):
                importlib.reload(creative_ad_simulation)
                with tempfile.TemporaryDirectory() as folder:
                    lib=Library(cache=Path(folder));self.assertTrue(lib.prompt.startswith('My custom copywriting direction'))
        finally:
            all_prompts.COPYWRITER=original;importlib.reload(creative_ad_simulation)
    def test_any_prompt_configuration_change_invalidates_creative_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(all_prompts,'fingerprint',return_value='configuration-one'):a=Library(cache=Path(folder)/'a')
            with patch.object(all_prompts,'fingerprint',return_value='configuration-two'):b=Library(cache=Path(folder)/'b')
            self.assertNotEqual(a.prompt_hash,b.prompt_hash)

if __name__=='__main__':unittest.main()
