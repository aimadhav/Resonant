import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from advertiser_inventory import advertisers,categories_for
from ad_simulation import exclusion_reasons
from live_cache import neutral_profile

class InventoryTests(unittest.TestCase):
    def test_briefs_are_unique_and_have_facts_cta(self):
        ads=advertisers();self.assertEqual(len(ads),30);self.assertEqual(len({a['id'] for a in ads}),30)
        for ad in ads:
            self.assertTrue(ad['fictional']);self.assertTrue(ad['approved_claims']);self.assertTrue(ad['approved_cta'])
    def test_matching_uses_whole_words(self):
        self.assertIn('therapy_app',categories_for('Therapy and counseling are part of this discussion'))
        self.assertIn('meditation_app',categories_for('We practice meditation'))
        self.assertIn('budgeting_app',categories_for('Shared household expenses and spending'))
        self.assertNotIn('reading_app',categories_for('already'))
        self.assertIn('gym_membership',categories_for('I go to the gym for lifting weights'))
        self.assertIn('personal_training',categories_for('Working with a personal trainer'))
        self.assertIn('running_club',categories_for('Running a marathon'))
    def test_subscription_exclusion_remains_effective(self):
        p=neutral_profile();p['hard_exclusions']['attributes']=['subscription_required']
        ad=next(a for a in advertisers() if a['id']=='quiet_minutes')
        self.assertTrue(exclusion_reasons(ad,p))

if __name__=='__main__':unittest.main()
