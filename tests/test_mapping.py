import unittest

from tests.helpers import ROOT  # noqa: F401  (sets sys.path)
from universe.hierarchy import Level, cosmic_name, level_for_depth
from universe.mapping import (MIN_FILE_RADIUS, MIN_FOLDER_RADIUS, file_kind, folder_kind, folder_layout, format_size,
                              stable_seed, visual_radius)

KB, MB, GB = 1024, 1024 ** 2, 1024 ** 3


class VisualRadiusTests(unittest.TestCase):
    def test_monotonic(self):
        sizes = [0, 1, 10, 5 * KB, MB, 100 * MB, GB, 100 * GB, 4 * 1024 * GB]
        radii = [visual_radius(s) for s in sizes]
        self.assertEqual(radii, sorted(radii))

    def test_examples_from_spec_are_distinct(self):
        r = [visual_radius(s) for s in (5 * KB, MB, 100 * MB, GB, 100 * GB)]
        for a, b in zip(r, r[1:]):
            self.assertGreater(b, a * 1.15, "each size class must be visibly larger")

    def test_nonlinear(self):
        # 1 TB is a million times 1 MB, but must not be a million times larger on screen
        self.assertLess(visual_radius(1024 * GB) / visual_radius(MB), 10)

    def test_minimums(self):
        self.assertEqual(visual_radius(0, is_dir=True), MIN_FOLDER_RADIUS)
        self.assertGreaterEqual(visual_radius(0), MIN_FILE_RADIUS)
        self.assertEqual(visual_radius(None, is_dir=True), MIN_FOLDER_RADIUS)
        self.assertGreater(MIN_FOLDER_RADIUS, 0)

    def test_format_size(self):
        self.assertEqual(format_size(0), "0 bytes")
        self.assertEqual(format_size(1536), "1.5 KB")
        self.assertEqual(format_size(5 * GB), "5.0 GB")
        self.assertEqual(format_size(None), "unknown")


class HierarchyTests(unittest.TestCase):
    def test_named_levels(self):
        self.assertEqual(level_for_depth(0), Level.UNIVERSE)
        self.assertEqual(level_for_depth(1), Level.GALAXY)
        self.assertEqual(level_for_depth(4), Level.SYSTEM)
        self.assertEqual(level_for_depth(5), Level.PLANET)
        self.assertEqual(level_for_depth(6), Level.MOON)
        self.assertEqual(level_for_depth(7), Level.CRATER)
        self.assertEqual(level_for_depth(9), Level.GRAIN)

    def test_unbounded_depth(self):
        for depth in list(range(0, 60)) + [500, 10_000]:
            self.assertTrue(folder_kind(depth))
            self.assertTrue(file_kind(depth))
            self.assertTrue(folder_layout(depth))
            self.assertTrue(cosmic_name(depth))
        self.assertIn("scale", cosmic_name(10_000))

    def test_kind_mapping(self):
        self.assertEqual(folder_kind(1), "galaxy")
        self.assertEqual(folder_kind(5), "planet")
        self.assertEqual(folder_kind(6), "moon")
        self.assertEqual(file_kind(4), "exoplanet")    # files in a planetary system
        self.assertEqual(file_kind(1), "star")

    def test_stable_seed(self):
        self.assertEqual(stable_seed("Windows"), stable_seed("windows"))
        self.assertNotEqual(stable_seed("a"), stable_seed("b"))


if __name__ == "__main__":
    unittest.main()
