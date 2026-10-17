# File Universe Explorer

A Windows desktop application that turns your real storage devices and their
folders into a navigable, real-time 3D universe. Each drive is a universe
shaped like its hardware. Inside it, folders become galaxies, nebulae, star
clusters, planetary systems, planets, moons, craters, rocks, sand grains and
then an endless microscopic world. Everything you see comes from your actual
disk: the names, paths, sizes, file types and folder relationships.

Browsing is **read-only**. The application never modifies, moves, renames or
deletes your files. Double-clicking a file (or pressing Enter on it) opens it
with its default application, just like Explorer.

## Setup (Windows 10/11, no administrator rights needed)

Requires Python 3.12 or newer from python.org (the `py` launcher) and a GPU/driver
with OpenGL 3.3, which every GPU from the last ~12 years supports.

```bat
py -m pip install -r requirements.txt
py main.py
```

To use an isolated environment instead:

```bat
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Optional: install **ffmpeg** (with `ffmpeg`/`ffprobe` on `PATH`) to get video
frame previews and waveforms for MP3/FLAC/OGG/M4A. Without it, video previews
fall back to Explorer's thumbnail cache, and WAV waveforms still work.

### Command-line options

| Command | Effect |
|---|---|
| `py main.py` | Start at *This PC* (all universes) |
| `py main.py --path "C:\Users"` | Start inside a folder |
| `py main.py --selftest OUT_DIR --tour C:\ @in @back ...` | Scripted tour that saves screenshots, then exits |

Environment variables: `FUE_GL_DEBUG=1` turns on PyOpenGL error checking.
`FUE_PERF_LOG=1` logs frames slower than 250 ms.

### Tests

```bat
py -m unittest discover -s tests -t .
```

There are 48 tests covering size calculation (deep nesting, long paths over
260 characters, Unicode names, junction cycles, cancellation and caching),
listing, search, layout geometry, scene building at depths 0–24, navigation
history, device classification, all mesh generators, the icon atlas and
image/audio previews. *(The suite uses `unittest`; `pytest` also works if you
have a working install.)*

## Using it

| Action | Mouse | Keyboard |
|---|---|---|
| Rotate | left-drag | arrow keys |
| Pan | right/middle-drag, or Shift+left-drag | W A S D |
| Zoom | wheel | + / − (PageUp/PageDown) |
| Select | click | Tab / Shift+Tab cycles objects |
| Enter folder / drive | double-click | Enter |
| Open file in its default app | double-click | Enter |
| Safely remove a USB/SD drive, eject a disc | right-click it in *Universes*, or toolbar ⏏ | Ctrl+E |
| Focus camera on selection | — | F |
| Back / forward / up | toolbar | Alt+← / Alt+→ / Alt+↑, Backspace |
| Home (*This PC*) | toolbar | Alt+Home / Home |
| Reset camera | toolbar | R / Ctrl+R |
| Refresh (rescan) | toolbar | F5 |
| Search | bottom dock | Ctrl+F |
| Go to path | toolbar | Ctrl+L |
| Toggle labels | toolbar | Ctrl+T |

* **Left sidebar**: the detected storage devices ("universes") and an
  **object list** of everything in the current view, with a filter. Clicking
  an entry selects it and flies the camera to it; double-clicking enters it.
  You never have to click tiny 3D objects. Folders too small to draw (folders
  with more than 20,000 entries) still appear in the list.
* **Breadcrumb bar**: click any ancestor to jump straight to it.
* **Properties panel**: real metadata for the selection (or for the current
  location when nothing is selected). Includes a preview for images, videos and
  audio.
* **Search**: case-insensitive name search (with `*`/`?` wildcards) below the
  current location, or on all drives from *This PC*. Results show the real
  path. Double-clicking a result flies there and selects it.
* **Status bar**: scanning/measuring progress with a **Cancel scan** button.

## How the filesystem maps to the cosmos

| Depth below drive root | Folder appears as | Files inside appear as | Layout of contents |
|---|---|---|---|
| 0 (drive) | Universe shaped like the device | Stars | Inside the device shell |
| 1 | Spiral galaxy | Stars | Along spiral arms |
| 2 | Galaxy region (nebula) | Stars | Nebula volume |
| 3 | Globular star cluster | Stars | Dense ball |
| 4 | Planetary system (star + orbit rings) | Exoplanets (image files are textured with the picture) | Keplerian orbits + asteroid belt |
| 5 | Planet (terrestrial or gas giant) | Crystals on the surface | Moons orbit, files on the surface |
| 6 | Moon | Crystals on the surface | Craters conform to the moon's surface |
| 7 | Crater (terrain bowl) | Pebbles | On the crater floor |
| 8 | Rock | Pebbles | Shells around the rock |
| 9 | Sand grain (quartz) | Particles | Shells |
| 10+ | Microbe → Molecule → Atom → Quantum particle → repeats at smaller scale, forever | Particles | Shells |

* **No depth limit.** The scene is always *re-rooted* at the current folder:
  the folder's own body sits at the origin with its children around it. Depth
  50 is therefore as precise and fast as depth 1. Entering a child zooms the
  camera into it, then swaps scenes so the same object becomes the new
  centre at the same apparent size. Going back zooms out the same way in
  reverse.
* **Folders stay recognisable as folders** at every level. They carry the
  (real) folder icon and cyan corner brackets, and folder labels are blue.
  Files carry their own file icon.
* **Devices**: SSD → slab with NAND chips and an M.2 gold edge connector;
  HDD → cylinder with platters, spindle and actuator arm; USB stick → body,
  metal connector and lanyard hole; CD/DVD/Blu-ray → disc with a centre hole;
  SD card → card outline with a clipped corner and gold contacts; network
  drives → a sphere with a ring; others → a generic box. The type comes from
  `GetDriveType` plus `Get-PhysicalDisk` (media type and bus type: NVMe, SATA,
  USB, SD) and falls back to heuristics.
* **Hot-plug**: drives are polled every 2 s through the cheap
  `GetLogicalDrives` bitmask. New drives fade in. When a removed drive is the
  one you are browsing, its universe fades away, a message appears, and you
  return to *This PC*; history entries on that drive are dropped.

### Size → visual size

`radius = 0.12 · 1.32^log10(bytes)`. This is monotonic and logarithmic-exponential:
1 KB ≈ 0.28, 1 MB ≈ 0.64, 100 MB ≈ 1.1, 1 GB ≈ 1.46, 100 GB ≈ 2.5,
1 TB ≈ 3.4 units. A terabyte is a trillion times a byte but only about 12 times
larger on screen. Folders have a minimum radius (empty folders stay visible),
and folders not yet measured use a placeholder size and then animate to their
true size. The properties panel always shows the **exact byte size**
separately from the **visual radius**, and estimates are marked with ≈.

## Architecture

```
main.py                     entry point, OpenGL 3.3 core context, --selftest tour
filesystem/  models.py      FSNode tree + LRU-bounded listing registry
             scanner.py     read-only os.scandir listing / sampling (worker-thread safe)
             sizes.py       iterative post-order size walk, SizeCache (mtime-validated LRU)
             search.py      BFS name search with wildcards, cancellation
             service.py     Qt service: worker threads -> queued signals; model mutated on GUI thread only
             paths.py       \\?\ long-path support, normalised keys, ancestors
             filetypes.py   extension -> category / colour
devices/     storage_info.py  capacity, labels, GetDriveType, Get-PhysicalDisk (SSD/HDD/USB/SD)
             detection.py     device listing + hot-plug monitor
universe/    hierarchy.py   depth -> cosmic level (unbounded)
             mapping.py     kinds, layouts, log size scaling, stable seeds
             procedural_generation.py  vectorised layouts (spiral, Vogel disk, ball, orbits, surface, bowl, device)
             scene_builder.py          FSNode -> Scene (GL-free, unit tested)
objects/     geometry.py    procedural meshes (spheres, icospheres, displacement, boxes, cylinders, tori, crystals)
             galaxy.py, star_cluster.py, planetary_system.py, planet.py, moon.py, crater.py,
             microscopic_objects.py, devices.py, registry.py
rendering/   renderer.py    instanced drawing per (kind, LOD), frustum culling, billboards
             shaders.py     GLSL: procedural planets/gas giants/moons/stars/rock/crystal/glass, nebula sky
             camera.py      smoothed orbit camera with log-distance fly-to animations
             scene.py       struct-of-arrays scene, orbit animation, LOD satellites
             lod.py, lighting.py, materials.py, textures.py (icon atlas, image textures), gl_utils.py
icons/       windows_icons.py  SHGetFileInfo + jumbo image list, IShellItemImageFactory (ctypes)
             loader.py         async icon service with canonical-key dedup + LRU
             generic.py        drawn fallback icons; texture_cache.py atlas slot allocator
previews/    images.py, video.py (ffmpeg / Explorer thumbnails), audio.py (waveforms), service.py
navigation/  controller.py (history, transition modes), selection.py
ui/          main_window.py, viewport.py (QOpenGLWidget, picking, transitions, labels),
             sidebar.py, properties_panel.py, breadcrumb.py, search_panel.py, qt_images.py
tests/       unittest suite
```

### Why PyQt6 + PyOpenGL (core profile)

PyQt6's `QOpenGLWidget` gives a native Windows desktop UI and a GL context in
the same widget tree. Its `QPainter` can draw crisp labels over the GL frame.
PyOpenGL with hand-written GLSL 3.30 shaders gives full control over instancing,
which is what makes tens of thousands of objects feasible from Python. Every
per-frame computation is vectorised with numpy: orbits, culling, LOD
selection and billboard placement. Higher-level engines (Panda3D, Ursina,
VisPy) were not needed and would add heavy dependencies or limit the UI
integration.

### Performance and safety design

* **Lazy scanning**: only the current folder is listed. Child folders are
  *sampled* (up to 48 entries each) to draw grandchildren as LOD satellites
  that appear only when their parent is large on screen.
* **Background workers**: listing (thread pool), sizes (dedicated thread,
  cancellable generations), search (cancellable thread), icons (2 threads with
  COM initialised), previews (2 threads) and device probing. The GUI thread
  never touches the disk except for a cheap `isdir` check on navigation.
* **Folder sizes are computed once.** Every completed sub-folder result is
  cached and validated by the folder's mtime, so going deeper reuses earlier
  measurements. Navigating cancels outstanding size jobs. Refresh (F5) clears
  the cache.
* **Bounded memory**: listing LRU (3,000 folders; ancestors of the current
  location are protected), size cache (400k entries), icon images (3,000), icon
  atlas (one 2048² texture with 1,024 slots, LRU-evicted, with generic icons
  pinned), image textures (40), previews (64). Folders with more than 100,000
  entries are truncated, and at most 20,000 children are drawn.
* **Rendering**: one instanced draw call per (kind, LOD). There are three mesh
  LODs chosen by projected pixel size, frustum culling, and sub-pixel culling.
  Distant particle clouds collapse to single sprites. Icons are capped at the
  180 largest visible objects and labels at 70, with overlap rejection.
* **Safety**: symbolic links, junctions and mount points are listed but never
  followed by size walks or searches, so directory cycles are impossible. A
  depth guard of 1,024 is also in place. Permission errors are counted and
  reported ("N folders skipped"), never fatal. Image decoding guards against
  decompression bombs (120 MP limit, 200 MB file limit). ffmpeg runs without a
  shell, reading the file as data. Files are only opened with their
  associated application when you double-click them (or press Enter).

## Limitations / known issues

* **No shadow mapping.** Planets in planetary systems get day/night shading
  from the central star, and other levels use a key light. Atmospheres, rims,
  glows and additive particles provide the depth cues.
* **SSD vs HDD detection** needs PowerShell's `Get-PhysicalDisk` (Storage
  module), which works without admin on Windows 10/11. If it is unavailable,
  fixed disks are shown as SSDs. Card-reader slots without media appear as
  dimmed USB devices because Windows reports them as removable without bus
  information.
* **Folder size accuracy**: sizes are logical file sizes (`st_size`), not
  allocated space. The mtime-based cache can miss changes deep inside a
  subtree until you press F5.
* Image textures are only wrapped onto **exoplanets** (files inside a
  planetary-system folder). At other levels, image files show the picture as
  their icon.
* Shell icon/thumbnail extraction can invoke third-party thumbnail handlers,
  the same code Explorer runs. Files are only opened when you double-click them.
* Very large folders (20k+ objects) stay interactive (about 40 fps on a GTX
  1650 for 20,000 point-cloud objects), but integrated GPUs may drop lower.
* Hot-plug was tested by simulating device removal (`--tour ... @unplug`).
  Physical removal goes through the same code path but was not exercised in
  the automated tests.
