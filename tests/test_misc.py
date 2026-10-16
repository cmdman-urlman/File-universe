import math
import os
import struct
import sys
import tempfile
import unittest
import wave

from PIL import Image

from tests.helpers import ROOT  # noqa: F401
from devices.storage_info import DISC, HDD, NETWORK, SDCARD, SSD, USB, classify
from icons.generic import generic_for_key
from icons.loader import generic_key
from icons.texture_cache import AtlasAllocator
from navigation.controller import History, Location, transition_mode
from objects.devices import BUILDERS, build_device, default_half
from objects.registry import KINDS


class NavigationTests(unittest.TestCase):
    def test_transition_modes(self):
        home = Location(None)
        c = Location("C:\\", "C:\\")
        win = Location("C:\\Windows", "C:\\")
        sys32 = Location("C:\\Windows\\System32", "C:\\")
        self.assertEqual(transition_mode(home, c), "in")
        self.assertEqual(transition_mode(c, win), "in")
        self.assertEqual(transition_mode(win, c), "out")
        self.assertEqual(transition_mode(c, home), "out")
        self.assertEqual(transition_mode(c, sys32), "jump")
        self.assertEqual(transition_mode(win, win), "refresh")
        self.assertEqual(transition_mode(None, c), "jump")

    def test_history(self):
        h = History()
        for p in (None, "C:\\", "C:\\a", "C:\\a\\b"):
            h.push(Location(p))
        self.assertEqual(h.back().path, "C:\\a")
        self.assertEqual(h.back().path, "C:\\")
        self.assertEqual(h.forward().path, "C:\\a")
        h.push(Location("C:\\x"))                  # branching drops forward entries
        self.assertFalse(h.can_forward())
        h.push(Location("C:\\x"))                  # duplicates ignored
        self.assertEqual(h.back().path, "C:\\a")

    def test_history_drops_missing_drives(self):
        h = History()
        h.push(Location(None))
        h.push(Location("E:\\stuff", "E:\\"))
        h.push(Location("C:\\", "C:\\"))
        h.replace_missing({"C:\\"})
        self.assertEqual(h.current.path, "C:\\")
        self.assertTrue(h.back().is_home)


class DeviceTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify(5, "", ""), DISC)
        self.assertEqual(classify(4, "", ""), NETWORK)
        self.assertEqual(classify(2, "", ""), USB)
        self.assertEqual(classify(2, "", "SD"), SDCARD)
        self.assertEqual(classify(3, "HDD", "SATA"), HDD)
        self.assertEqual(classify(3, "SSD", "NVMe"), SSD)
        self.assertEqual(classify(3, "Unspecified", "USB"), USB)

    def test_every_device_shape_builds(self):
        for kind in BUILDERS:
            shell, details, edges = build_device(kind, default_half(kind))
            self.assertGreater(len(shell.indices), 0, kind)
            self.assertGreater(len(edges.indices), 0, kind)
            self.assertIsInstance(details, list)


class ObjectKindTests(unittest.TestCase):
    def test_all_kinds_build_all_lods(self):
        for name, spec in KINDS.items():
            for build in spec.lods:
                m = build()
                self.assertGreater(len(m.positions), 0, name)
                self.assertEqual(m.vertex_array().shape[1], 8)
            if spec.lines:
                self.assertGreater(len(spec.lines().indices), 0)


class AtlasTests(unittest.TestCase):
    def test_lru_and_pinning(self):
        a = AtlasAllocator(atlas_size=256, cell=64)    # 16 slots
        a.allocate("pinned", pinned=True)
        for i in range(15):
            a.allocate(f"k{i}")
        self.assertEqual(len(a), 16)
        a.get("k0")                                    # k0 recently used
        slot, evicted = a.allocate("new")
        self.assertEqual(evicted, "k1")
        self.assertIn("pinned", a)
        u0, v0, u1, v1 = a.uv_rect(slot)
        self.assertTrue(0 <= u0 < u1 <= 1 and 0 <= v0 < v1 <= 1)

    def test_generic_icons(self):
        for key in ("gen:folder", "gen:image:jpg", "gen:drive:usb", "gen:other:"):
            img = generic_for_key(key)
            self.assertEqual(img.size, (64, 64))
            self.assertEqual(img.mode, "RGBA")
        self.assertEqual(generic_key("dir:C:\\x"), "gen:folder")
        self.assertEqual(generic_key("file:C:\\x\\song.MP3"), "gen:audio:mp3")


class PreviewTests(unittest.TestCase):
    def test_image_thumbnail_and_texture(self):
        from previews.images import load_thumbnail, planet_texture
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "pic.png")
            Image.new("RGBA", (800, 400), (10, 200, 30, 0)).save(p)
            thumb, dims = load_thumbnail(p, 128)
            self.assertEqual(dims, (800, 400))
            self.assertEqual(max(thumb.size), 128)
            tex = planet_texture(thumb)
            self.assertEqual(tex.size, (512, 256))
            self.assertEqual(tex.getpixel((5, 5))[:3], (0, 0, 0))   # transparent -> black, not hidden colour

    def test_corrupt_image_is_safe(self):
        from previews.images import load_thumbnail
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "broken.jpg")
            with open(p, "wb") as f:
                f.write(b"not really a jpeg")
            self.assertEqual(load_thumbnail(p), (None, None))

    def test_wav_waveform(self):
        from previews.audio import waveform_image
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "tone.wav")
            with wave.open(p, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(i / 10))) for i in range(8000)))
            img, dur = waveform_image(p)
            self.assertIsNotNone(img)
            self.assertAlmostEqual(dur, 1.0, places=2)


@unittest.skipUnless(sys.platform == "win32", "Windows shell icons")
class WindowsIconTests(unittest.TestCase):
    def test_system_icons(self):
        from icons.windows_icons import com_init, system_icon
        com_init()
        res = system_icon(os.environ.get("SystemRoot", "C:\\Windows"), True, 64)
        self.assertIsNotNone(res)
        img, type_name = res
        self.assertEqual(img.size, (64, 64))
        self.assertGreater(img.getextrema()[3][1], 0)       # has visible pixels
        res = system_icon("file.txt", False, 64, by_attributes=True)
        self.assertIsNotNone(res)


if __name__ == "__main__":
    unittest.main()
