import itertools
import unittest

import numpy as np

from tests.helpers import ROOT  # noqa: F401
from filesystem.models import FSNode, PreviewEntry
from universe import procedural_generation as pg
from universe.scene_builder import MAX_RENDERED_CHILDREN, build_folder_scene, build_home_scene, layout_folder_scene


def min_gap(pos, radii):
    """Smallest (distance - r_i - r_j) over all pairs."""
    best = np.inf
    for i, j in itertools.combinations(range(len(pos)), 2):
        best = min(best, np.linalg.norm(pos[i] - pos[j]) - radii[i] - radii[j])
    return best


def synthetic_folder(n_dirs=5, n_files=8, name="root", path="C:\\root") -> FSNode:
    node = FSNode(path=path, name=name, is_dir=True)
    kids = []
    for i in range(n_dirs):
        d = FSNode(path=f"{path}\\dir{i}", name=f"dir{i}", is_dir=True, parent=node)
        d.total_size = 10 ** (3 + i)
        d.preview = [PreviewEntry(f"p{k}", k % 2 == 0, 1000 * k) for k in range(6)]
        kids.append(d)
    for i in range(n_files):
        kids.append(FSNode(path=f"{path}\\f{i}.jpg", name=f"f{i}.jpg", is_dir=False, size=500 * (i + 1), parent=node))
    node.children = kids
    return node


class LayoutTests(unittest.TestCase):
    def test_layouts_have_no_nans_and_right_shape(self):
        rng = np.random.default_rng(1)
        for n in (0, 1, 7, 300):
            radii = rng.uniform(0.1, 2.0, n)
            seeds = rng.random(n)
            for lay in (pg.vogel_disk(radii, seeds), pg.vogel_disk(radii, seeds, arms=3, twist=3, jitter=0.3),
                        pg.ball(radii, seeds, inner=2), pg.orbits(radii, seeds, inner=3),
                        pg.surface(radii, seeds, 5.0), pg.bowl(radii, seeds, 2.0)[0],
                        pg.device_layout(radii, seeds, "usb")[0]):
                self.assertEqual(lay.positions.shape, (n, 3))
                self.assertFalse(np.isnan(lay.positions).any())

    def test_vogel_and_orbit_spacing(self):
        radii = np.full(60, 0.5)
        seeds = np.linspace(0, 1, 60)
        self.assertGreater(min_gap(pg.vogel_disk(radii, seeds).positions, radii), -0.05)
        orb = pg.orbits(radii[:10], seeds[:10], inner=2.0)
        self.assertGreater(min_gap(orb.positions, radii[:10]), -1e-6)

    def test_extent_grows_with_count(self):
        e = [pg.vogel_disk(np.full(n, 0.5), np.zeros(n)).extent for n in (10, 100, 1000)]
        self.assertTrue(e[0] < e[1] < e[2])

    def test_device_shell_contains_layout(self):
        radii = np.full(40, 0.6)
        for kind in ("ssd", "hdd", "usb", "disc", "sd"):
            lay, half = pg.device_layout(radii, np.linspace(0, 1, 40), kind)
            self.assertTrue(np.all(np.abs(lay.positions[:, 0]) <= half[0] + 1e-6), kind)
            self.assertTrue(np.all(np.abs(lay.positions[:, 2]) <= half[2] + 1e-6), kind)

    def test_surface_on_sphere(self):
        radii = np.full(20, 0.3)
        lay = pg.surface(radii, np.zeros(20), 4.0, embed=1.0)
        np.testing.assert_allclose(np.linalg.norm(lay.positions, axis=1), 4.0, rtol=1e-5)
        a, b = pg.orientation_from_normals(lay.normals)
        # rotating +Y by X then Z must give the normal
        up = np.stack([-np.cos(a) * np.sin(b), np.cos(a) * np.cos(b), np.sin(a)], 1)
        np.testing.assert_allclose(up, lay.normals, atol=1e-5)


class SceneTests(unittest.TestCase):
    def test_scene_at_every_depth(self):
        for depth in range(0, 25):
            sc = build_folder_scene(synthetic_folder(), depth, "ssd")
            self.assertEqual(len(sc), 1 + 13)
            self.assertTrue(sc.items[0].is_center)
            self.assertFalse(np.isnan(sc.target_pos).any(), depth)
            self.assertGreater(sc.view_distance, 0)
            self.assertTrue(all(it.is_dir for it in sc.items[1:6]))
            self.assertEqual(len(sc.sat_parent), 5 * 6)

    def test_bigger_data_is_bigger_object(self):
        sc = build_folder_scene(synthetic_folder(), 3)
        dirs = sc.radius_target[1:6]
        self.assertTrue(np.all(np.diff(dirs) > 0))

    def test_empty_folder_and_unmeasured_are_visible(self):
        node = FSNode(path="C:\\e", name="e", is_dir=True)
        node.children = [FSNode(path="C:\\e\\x", name="x", is_dir=True, parent=node)]
        sc = build_folder_scene(node, 2)
        self.assertGreater(sc.radius_target[1], 0.2)
        empty = FSNode(path="C:\\e2", name="e2", is_dir=True)
        empty.children = []
        sc2 = build_folder_scene(empty, 5)
        self.assertEqual(len(sc2), 1)
        self.assertGreater(sc2.radius_target[0], 0)

    def test_huge_folder_is_capped(self):
        node = FSNode(path="C:\\big", name="big", is_dir=True)
        node.children = [FSNode(path=f"C:\\big\\f{i}", name=f"f{i}", is_dir=False, size=i, parent=node)
                         for i in range(MAX_RENDERED_CHILDREN + 500)]
        sc = build_folder_scene(node, 2)
        self.assertEqual(len(sc), MAX_RENDERED_CHILDREN + 1)
        self.assertEqual(sc.hidden_count, 500)

    def test_relayout_after_sizes(self):
        node = synthetic_folder()
        sc = build_folder_scene(node, 4)
        before = sc.radius_target[1]
        node.children[0].total_size = 50 * 1024 ** 3
        layout_folder_scene(sc)
        self.assertGreater(sc.radius_target[1], before)

    def test_home_scene(self):
        from devices.storage_info import DeviceInfo
        devs = [DeviceInfo("C:\\", "C:", total=500 * 10 ** 9, kind="ssd"),
                DeviceInfo("E:\\", "E:", total=16 * 10 ** 9, kind="usb"),
                DeviceInfo("F:\\", "F:", kind="disc", ready=False)]
        sc = build_home_scene(devs)
        self.assertEqual(len(sc), 3)
        self.assertEqual(sc.items[0].kind, "device:ssd")
        self.assertGreater(sc.radius_target[0], sc.radius_target[1])   # bigger capacity, bigger universe
        self.assertEqual(sc.index_of_key(devs[1].key), 1)


if __name__ == "__main__":
    unittest.main()
