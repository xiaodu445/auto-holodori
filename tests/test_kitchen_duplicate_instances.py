import unittest,json
from pathlib import Path
from modular_agent.realtime.kitchen_match import Item,duplicate_candidate
ROOT=Path(__file__).resolve().parents[1]
class DuplicateInstancesTests(unittest.TestCase):
    def test_reviewed_displaced_seaweed_is_one_instance(self):
        a=Item('a','seaweed',545,307,.94,(441,214,618,354))
        b=Item('b','seaweed',485,287,.72,(408,213,546,369))
        self.assertTrue(duplicate_candidate(a,b))
    def test_highly_overlapping_competing_classes_do_not_count_twice(self):
        a=Item('a','noodle_pan',780,440,.9,(733,395,848,499))
        b=Item('b','instant_noodles',790,460,.27,(733,397,848,499))
        self.assertTrue(duplicate_candidate(a,b))
    def test_real_stacked_instances_with_distinct_points_are_kept(self):
        a=Item('a','seaweed',15,20,.9,(0,0,100,100))
        b=Item('b','seaweed',95,85,.9,(20,0,120,100))
        self.assertFalse(duplicate_candidate(a,b))
    def test_overlap_between_different_items_is_not_enough_to_suppress(self):
        a=Item('a','onion',20,30,.9,(0,0,100,100))
        b=Item('b','Yellow_egg',90,70,.9,(30,0,130,100))
        self.assertFalse(duplicate_candidate(a,b))
