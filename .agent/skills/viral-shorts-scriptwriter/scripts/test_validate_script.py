import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_script import validate

GOOD = ("In 1925, a con man sold the Eiffel Tower. Then he sold it again. "
 "Victor Lustig read a newspaper story about the tower's repair bills. "
 "He forged government letters and invited six scrap dealers to a Paris hotel. "
 "He claimed the city secretly wanted the tower torn down and sold for metal. "
 "One dealer, André Poisson, wanted the deal badly. "
 "Poisson paid the bribe and the full price, and Lustig vanished to Vienna. "
 "Poisson was too embarrassed to call the police. So Lustig came back and tried it again. "
 "Years later, in Chicago, he borrowed fifty thousand dollars from Al Capone. "
 "He locked it in a vault for two months, then returned every cent. "
 "Capone was so impressed he handed Lustig five thousand dollars. "
 "The man who sold the Eiffel Tower twice had even conned a gangster into paying for honesty.")

class T(unittest.TestCase):
    def test_good_passes(self):
        r = validate(GOOD, wps=2.6)
        self.assertTrue(r["ok"], r)
    def test_science_fails(self):
        r = validate(GOOD.replace("con man", "biologist"), wps=2.6)
        self.assertFalse(r["ok"])
    def test_too_short_fails(self):
        self.assertFalse(validate("In 1925, a con man sold the Eiffel Tower. Then he sold it again.")["ok"])
    def test_slop_fails(self):
        self.assertFalse(validate(GOOD + " Like and subscribe for more.")["ok"])
    def test_weak_opener_fails(self):
        self.assertFalse(validate("Did you know a man sold the Eiffel Tower? " + GOOD)["ok"])
    def test_beats_input(self):
        beats = [s.strip() for s in GOOD.split(". ") if s.strip()]
        self.assertIn("est_seconds", validate({"beats": beats}))

if __name__ == "__main__":
    unittest.main()
