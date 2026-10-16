import os
import subprocess
import sys
import threading
import unittest

from tests.helpers import TempTree
from filesystem.models import FileSystemModel, ScanState
from filesystem.paths import depth_below, is_ancestor, norm_key, os_path, parent_path, split_ancestors
from filesystem.scanner import list_directory, sample_directory
from filesystem.search import search_tree
from filesystem.sizes import SizeCache, compute_tree_size

TREE = {
    "a.txt": 100,
    "b.bin": 2000,
    "empty": {},
    "sub": {"c.txt": 300, "deeper": {"d.txt": 400, "e.png": 50}},
    "ünïcödé 文件夹": {"файл.txt": 7},
}
TOTAL = 100 + 2000 + 300 + 400 + 50 + 7


def make_junction(link: str, target: str) -> bool:
    """Directory junctions need no admin rights on Windows."""
    if sys.platform != "win32":
        try:
            os.symlink(target, link, target_is_directory=True)
            return True
        except OSError:
            return False
    r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
    return r.returncode == 0


class ListingTests(unittest.TestCase):
    def test_list_directory(self):
        with TempTree(TREE) as root:
            entries, err = list_directory(root)
            self.assertIsNone(err)
            names = {e.name: e for e in entries}
            self.assertEqual(set(names), set(TREE))
            self.assertTrue(names["sub"].is_dir)
            self.assertFalse(names["a.txt"].is_dir)
            self.assertEqual(names["b.bin"].size, 2000)
            self.assertIsNotNone(names["a.txt"].mtime)

    def test_missing_directory_reports_error(self):
        entries, err = list_directory(os.path.join("Z:\\", "definitely", "not", "here"))
        self.assertEqual(entries, [])
        self.assertTrue(err)

    def test_sample_directory(self):
        with TempTree({f"f{i}.txt": i for i in range(100)}) as root:
            sample, total = sample_directory(root, limit=10)
            self.assertEqual(len(sample), 10)
            self.assertEqual(total, 100)

    def test_large_directory(self):
        with TempTree({f"file_{i:05d}.dat": 1 for i in range(3000)}) as root:
            entries, err = list_directory(root)
            self.assertEqual(len(entries), 3000)
            entries, err = list_directory(root, max_entries=500)
            self.assertEqual(len(entries), 500)
            self.assertIn("500", err)

    def test_long_paths(self):
        with TempTree({}) as root:
            deep = root
            for i in range(12):
                deep = os.path.join(deep, f"long_folder_name_number_{i:02d}_xxxxxxxx")
            os.makedirs(os_path(deep))
            with open(os_path(os.path.join(deep, "leaf.txt")), "wb") as f:
                f.write(b"12345")
            self.assertGreater(len(deep), 260)
            entries, err = list_directory(deep)
            self.assertIsNone(err)
            self.assertEqual(entries[0].size, 5)
            res = compute_tree_size(root)
            self.assertEqual(res.total, 5)
            self.assertEqual(res.dirs, 12)


class SizeTests(unittest.TestCase):
    def test_tree_size(self):
        with TempTree(TREE) as root:
            res = compute_tree_size(root)
            self.assertTrue(res.complete)
            self.assertEqual(res.total, TOTAL)
            self.assertEqual(res.files, 6)
            self.assertEqual(res.dirs, 4)       # empty, sub, sub/deeper, unicode

    def test_deep_nesting_no_recursion_limit(self):
        with TempTree({}) as root:
            p = root
            for i in range(60):
                p = os.path.join(p, "d")
            os.makedirs(os_path(p))
            with open(os_path(os.path.join(p, "x")), "wb") as f:
                f.write(b"abc")
            res = compute_tree_size(root)
            self.assertEqual(res.total, 3)
            self.assertEqual(res.dirs, 60)

    def test_cache_reuse(self):
        with TempTree(TREE) as root:
            cache = SizeCache()
            first = compute_tree_size(root, cache=cache)
            self.assertGreater(len(cache), 0)
            sub = cache.get(os.path.join(root, "sub"))
            self.assertIsNotNone(sub)
            self.assertEqual(sub.total, 750)
            again = compute_tree_size(root, cache=cache)
            self.assertIs(again, cache.get(root))
            self.assertEqual(first.total, again.total)

    def test_cancellation(self):
        with TempTree(TREE) as root:
            ev = threading.Event()
            ev.set()
            res = compute_tree_size(root, cancel=ev)
            self.assertFalse(res.complete)

    def test_cache_bound(self):
        cache = SizeCache(max_entries=3)
        from filesystem.sizes import SizeResult
        for i in range(10):
            cache.put(f"C:\\x{i}", SizeResult(i), None)
        self.assertEqual(len(cache), 3)

    def test_junction_cycle_not_followed(self):
        with TempTree(TREE) as root:
            link = os.path.join(root, "sub", "deeper", "loop")
            if not make_junction(link, root):
                self.skipTest("cannot create junction/symlink here")
            res = compute_tree_size(root)
            self.assertEqual(res.total, TOTAL)       # the cycle adds nothing
            entries, _ = list_directory(os.path.join(root, "sub", "deeper"))
            loop = [e for e in entries if e.name == "loop"][0]
            self.assertTrue(loop.is_link)


class SearchTests(unittest.TestCase):
    def test_substring_and_wildcard(self):
        with TempTree(TREE) as root:
            hits = search_tree(root, "TXT")
            self.assertEqual({h.name for h in hits}, {"a.txt", "c.txt", "d.txt", "файл.txt"})
            hits = search_tree(root, "*.png")
            self.assertEqual([h.name for h in hits], ["e.png"])
            hits = search_tree(root, "deep")
            self.assertTrue(hits[0].is_dir)
            self.assertTrue(hits[0].path.endswith("deeper"))

    def test_limit_and_cancel(self):
        with TempTree({f"x{i}.txt": 1 for i in range(50)}) as root:
            self.assertEqual(len(search_tree(root, "x", max_results=10)), 10)
            ev = threading.Event()
            ev.set()
            self.assertEqual(search_tree(root, "x", cancel=ev), [])


class ModelTests(unittest.TestCase):
    def test_apply_listing_and_identity(self):
        with TempTree(TREE) as root:
            m = FileSystemModel()
            entries, err = list_directory(root)
            node = m.apply_listing(root, entries, err)
            self.assertEqual(node.list_state, ScanState.COMPLETE)
            self.assertTrue(node.children[0].is_dir)            # folders first
            sub = m.get(os.path.join(root, "sub"))
            self.assertIs(sub.parent, node)
            node2 = m.apply_listing(root, *list_directory(root))
            self.assertIs(node2, node)
            self.assertIs(m.get(os.path.join(root, "sub")), sub)  # identity preserved on rescan
            f, d = node.direct_counts()
            self.assertEqual((f, d), (2, 3))

    def test_lru_eviction_protects_ancestors(self):
        m = FileSystemModel(max_listed_dirs=2)
        m.apply_listing("C:\\keep", [], None)
        m.apply_listing("C:\\b", [], None, protected={norm_key("C:\\keep")})
        m.apply_listing("C:\\c", [], None, protected={norm_key("C:\\keep")})
        self.assertIsNotNone(m.get("C:\\keep").children)
        self.assertIsNone(m.get("C:\\b").children)


class PathTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(split_ancestors("C:\\a\\b"), ["C:\\", "C:\\a", "C:\\a\\b"])
        self.assertEqual(depth_below("C:\\", "C:\\a\\b"), 2)
        self.assertEqual(depth_below("C:\\", "C:\\"), 0)
        self.assertTrue(is_ancestor("C:\\a", "C:\\a\\b"))
        self.assertFalse(is_ancestor("C:\\a", "C:\\ab"))
        self.assertIsNone(parent_path("C:\\"))
        self.assertEqual(norm_key("c:\\Windows"), norm_key("C:\\WINDOWS\\"))


if __name__ == "__main__":
    unittest.main()
