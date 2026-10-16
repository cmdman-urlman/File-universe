"""The OpenGL renderer: draws a :class:`~rendering.scene.Scene` each frame.

Objects are grouped by (kind, LOD) and drawn with one instanced draw call per
group; everything per-frame (orbits, frustum culling, LOD choice, billboards)
is computed with vectorised numpy, so tens of thousands of objects stay fast.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from OpenGL import GL as gl

from objects.base import S_GLASS, S_TEXTURED
from objects.devices import build_device, default_half
from objects.geometry import POINTS, MeshData, circle_lines
from objects.registry import KINDS

from . import lod as lodmod
from . import materials as mat
from .gl_utils import BillboardBatch, GPUMesh, ShaderProgram
from .lighting import lighting_for
from .mathutil import frustum_planes, project, spheres_in_frustum
from .shaders import (BACKGROUND_FS, BACKGROUND_VS, BILLBOARD_FS, BILLBOARD_VS, LINE_FS, LINE_VS, MESH_FS,
                      MESH_VS, POINTS_FS, POINTS_VS)
from .textures import IconAtlas, ImageTextures

BACKDROP_KINDS = {"galaxy", "region", "cluster", "crater"}


@dataclass
class FrameInfo:
    positions: np.ndarray
    radii: np.ndarray
    screen: np.ndarray        # device pixels
    px: np.ndarray            # projected radius, device pixels
    visible: np.ndarray
    depth: np.ndarray
    width: int
    height: int


def _instances(pos, scale, tilt, spin, squash, col, seed, style, hl, emis) -> np.ndarray:
    n = len(pos)
    a = np.empty((n, 16), np.float32)
    a[:, 0:3] = pos
    a[:, 3] = scale
    a[:, 4:6] = tilt
    a[:, 6] = spin
    a[:, 7] = squash
    a[:, 8:12] = col
    a[:, 12] = seed
    a[:, 13] = style
    a[:, 14] = hl
    a[:, 15] = emis
    return a


def _billboards(pos, size, col, uv, mode, yoff=0.0, rot=0.0, extra=0.0) -> np.ndarray:
    n = len(pos)
    a = np.zeros((n, 16), np.float32)
    a[:, 0:3] = pos
    a[:, 3] = size
    a[:, 4:8] = col
    a[:, 8:12] = uv
    a[:, 12] = mode
    a[:, 13] = yoff
    a[:, 14] = rot
    a[:, 15] = extra
    return a


class Renderer:
    def __init__(self, icon_service, preview_service):
        self.icon_service = icon_service
        self.preview_service = preview_service
        self.ready = False
        self.kind_names: list[str] = []
        self.kind_codes: dict[str, int] = {}

    # ---- setup ---------------------------------------------------------------
    def initialize(self) -> None:
        self.p_mesh = ShaderProgram(MESH_VS, MESH_FS)
        self.p_line = ShaderProgram(LINE_VS, LINE_FS)
        self.p_points = ShaderProgram(POINTS_VS, POINTS_FS)
        self.p_bill = ShaderProgram(BILLBOARD_VS, BILLBOARD_FS)
        self.p_bg = ShaderProgram(BACKGROUND_VS, BACKGROUND_FS)
        self.bg_vao = gl.glGenVertexArrays(1)
        self.meshes: dict[tuple[str, int], GPUMesh] = {}
        self.line_meshes: dict[str, GPUMesh] = {}
        self.device_meshes: dict[tuple, tuple] = {}
        self.circle = GPUMesh(circle_lines(160))
        self.billboards = BillboardBatch()
        rng = np.random.default_rng(99)
        dust_pos = rng.uniform(-1, 1, (2500, 3)).astype(np.float32)
        dust = MeshData(dust_pos, mode=POINTS, colors=np.full((2500, 3), 0.8, np.float32),
                        sizes=np.column_stack([np.full(2500, 0.0025), rng.uniform(0.15, 0.5, 2500)]).astype(np.float32))
        self.dust = GPUMesh(dust)
        self.atlas = IconAtlas(self.icon_service)
        self.images = ImageTextures(self.preview_service)
        gl.glEnable(gl.GL_PROGRAM_POINT_SIZE)
        self.ready = True

    def code_of(self, kind: str) -> int:
        c = self.kind_codes.get(kind)
        if c is None:
            c = len(self.kind_names)
            self.kind_names.append(kind)
            self.kind_codes[kind] = c
        return c

    def _mesh(self, kind: str, lod: int) -> GPUMesh:
        key = (kind, lod)
        m = self.meshes.get(key)
        if m is None:
            spec = KINDS[kind]
            m = GPUMesh(spec.lods[min(lod, len(spec.lods) - 1)]())
            self.meshes[key] = m
        return m

    def _line_mesh(self, kind: str) -> GPUMesh | None:
        if kind not in self.line_meshes:
            spec = KINDS.get(kind)
            self.line_meshes[kind] = GPUMesh(spec.lines()) if spec and spec.lines else None
        return self.line_meshes[kind]

    def _device(self, kind: str, half) -> tuple:
        key = (kind, tuple(round(h, 2) for h in half))
        d = self.device_meshes.get(key)
        if d is None:
            shell, details, edges = build_device(kind, half)
            d = (GPUMesh(shell), [(GPUMesh(m), style) for m, style in details], GPUMesh(edges))
            if len(self.device_meshes) > 24:
                for old in list(self.device_meshes.values())[:8]:
                    old[0].delete()
                    old[2].delete()
                    for m, _ in old[1]:
                        m.delete()
                self.device_meshes = dict(list(self.device_meshes.items())[8:])
            self.device_meshes[key] = d
        return d

    def _scene_codes(self, scene) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        cache = scene.extra.get("_codes")
        if cache is None or cache[0] != len(scene.items) or cache[4] != len(scene.sat_kind):
            codes = np.array([self.code_of(it.kind) for it in scene.items], np.int32)
            sat_codes = np.array([self.code_of(k) for k in scene.sat_kind], np.int32)
            drawn = np.array([it.drawn for it in scene.items], bool)
            cache = (len(scene.items), codes, sat_codes, drawn, len(scene.sat_kind))
            scene.extra["_codes"] = cache
        return cache[1], cache[2], cache[3]

    # ---- frame ---------------------------------------------------------------
    def render(self, scene, cam, width: int, height: int, t: float, scene_t: float,
               selected: int | None, hovered: int | None) -> FrameInfo | None:
        gl.glViewport(0, 0, width, height)
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        aspect = width / max(height, 1)
        view = cam.view()
        proj = cam.projection(aspect)
        vp = proj @ view
        eye = cam.eye()
        right, up, fwd = cam.basis()
        self._background(view, proj, scene.nebula_hue if scene else 0.62, t)
        if scene is None or len(scene) == 0:
            return None
        self.atlas.begin_frame()
        light = lighting_for(scene)

        pos = scene.world_positions(scene_t).astype(np.float64)
        rad = scene.radius.astype(np.float64)
        depth = (pos - eye) @ fwd
        ppu = cam.pixels_per_unit(np.abs(depth), height)
        px = rad * ppu
        codes, sat_codes, drawn = self._scene_codes(scene)
        planes = frustum_planes(vp)
        vis = spheres_in_frustum(planes, pos, rad * 1.4) & (px > lodmod.CULL_PX) & (depth > -rad)
        alpha = scene.alpha * scene.fade
        keep = scene.extra.get("keep")
        if keep is not None:
            alpha[keep] = scene.alpha[keep]
        col = scene.color.copy()
        col[:, 3] *= alpha
        hl = np.zeros(len(scene), np.float32)
        if hovered is not None and 0 <= hovered < len(hl):
            hl[hovered] = 0.45
        if selected is not None and 0 <= selected < len(hl):
            hl[selected] = 1.0
        spin = scene_t * scene.spin + scene.seed * 6.283

        # satellites (sampled grandchildren) appear when their parent is big on screen
        ns = len(scene.sat_parent)
        if ns:
            par = scene.sat_parent
            spos = scene.satellite_positions(scene_t, pos)
            srad = scene.sat_radius * rad[par]
            sdepth = (spos - eye) @ fwd
            spx = srad * cam.pixels_per_unit(np.abs(sdepth), height)
            salpha = lodmod.satellite_alpha(px[par]) * alpha[par] * vis[par]
            svis = (salpha > 0.01) & spheres_in_frustum(planes, spos, srad * 1.4) & (spx > lodmod.CULL_PX)
            scol = scene.sat_color.copy()
            scol[:, 3] *= salpha
        else:
            spos = np.zeros((0, 3))
            srad = spx = salpha = np.zeros(0)
            svis = np.zeros(0, bool)
            scol = np.zeros((0, 4))

        item_draw = vis & drawn & (alpha > 0.003)
        # textured image planets are drawn individually
        textured = []
        for i in np.nonzero(item_draw & (px > 14))[0][:64]:
            it = scene.items[i]
            if it.image_texture:
                tex = self.images.get(it.image_texture)
                if tex is not None:
                    textured.append((i, tex))
                    if len(textured) >= 24:
                        break
        tex_mask = np.zeros(len(scene), bool)
        for i, _ in textured:
            tex_mask[i] = True

        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDisable(gl.GL_CULL_FACE)

        m = self.p_mesh
        m.use()
        m.mat4("u_view", view)
        m.mat4("u_proj", proj)
        m.vec3("u_eye", eye)
        m.vec3("u_light_pos", light.light_pos)
        m.i("u_star_light", 1 if light.star_light else 0)
        m.f("u_time", t)
        m.f("u_alpha", 1.0)
        m.i("u_tex", 1)

        # ---- solid meshes -------------------------------------------------
        sel_items = np.nonzero(item_draw & ~tex_mask)[0]
        sel_sats = np.nonzero(svis)[0]
        point_jobs = []
        glow_jobs = []
        for code in np.unique(np.concatenate([codes[sel_items], sat_codes[sel_sats]])) if (len(sel_items) or len(sel_sats)) else []:
            kind = self.kind_names[code]
            ii = sel_items[codes[sel_items] == code]
            ss = sel_sats[sat_codes[sel_sats] == code]
            if kind.startswith("device:"):
                self._draw_home_devices(scene, kind[7:], ii, pos, col, hl, t)
                continue
            spec = KINDS.get(kind)
            if spec is None:
                continue
            P = np.concatenate([pos[ii], spos[ss]])
            R = np.concatenate([rad[ii], srad[ss]])
            PX = np.concatenate([px[ii], spx[ss]])
            C = np.concatenate([col[ii], scol[ss]])
            T = np.concatenate([scene.tilt[ii], np.zeros((len(ss), 2))])
            S = np.concatenate([spin[ii], scene_t * 0.2 + scene.sat_seed[ss] * 6.283])
            Q = np.concatenate([scene.squash[ii], np.ones(len(ss))])
            SEED = np.concatenate([scene.seed[ii], scene.sat_seed[ss]])
            STY = np.concatenate([scene.style[ii], scene.sat_style[ss]])
            HL = np.concatenate([hl[ii], np.zeros(len(ss))])
            EM = np.concatenate([scene.emissive[ii], np.full(len(ss), spec.emissive)])
            inst = _instances(P, R, T, S, Q, C, SEED, STY, HL, EM)
            if spec.glow > 0:
                glow_jobs.append((P, R * spec.glow, C))
            if spec.draw == "points":
                point_jobs.append((kind, inst, PX))
                continue
            lods = lodmod.choose_lod(PX)
            for lv in (0, 1, 2):
                sel = lods == lv
                if sel.any():
                    self._mesh(kind, lv).draw(inst[sel])

        # ---- textured image planets ----------------------------------------
        for i, tex in textured:
            gl.glActiveTexture(gl.GL_TEXTURE1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            inst = _instances(pos[i:i + 1], rad[i:i + 1], scene.tilt[i:i + 1], spin[i:i + 1], scene.squash[i:i + 1],
                              col[i:i + 1], scene.seed[i:i + 1], [S_TEXTURED], hl[i:i + 1], [0.0])
            self._mesh(scene.items[i].kind, 0).draw(inst)
        gl.glActiveTexture(gl.GL_TEXTURE0)

        # ---- universe shell details (opaque) --------------------------------
        shell = scene.shell
        if shell is not None:
            dkind, half, rgb = shell
            dm = self._device(dkind, half)
            m.use()
            for dmesh, style in dm[1]:
                dinst = _instances([[0, 0, 0]], [1.0], [[0, 0]], [0], [1], [(*mat.DETAIL_COLOR, 0.95 * scene.fade)],
                                   [0.3], [style], [0], [0.0])
                dmesh.draw(dinst)

        # ---- lines: orbits, belts, decorations, device edges -----------------
        self._lines(scene, pos, rad, col, spin, item_draw, codes, view, proj, alpha)

        # ---- particles (additive) --------------------------------------------
        gl.glDepthMask(gl.GL_FALSE)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE)
        p = self.p_points
        p.use()
        p.mat4("u_view", view)
        p.mat4("u_proj", proj)
        p.f("u_px_scale", height * 0.5 / math.tan(math.radians(cam.FOV) / 2))
        p.f("u_alpha", 1.0)
        dscale = max(scene.extent * 3.0, 10.0)
        self.dust.draw(_instances([[0, 0, 0]], [dscale], [[0, 0]], [0], [1], [(0.8, 0.85, 1.0, 0.6 * scene.fade)],
                                  [0], [0], [0], [0]))
        dots = []
        for kind, inst, PX in point_jobs:
            tiny = PX < lodmod.POINT_CLOUD_MIN_PX
            if tiny.any():
                dots.append(inst[tiny])
                inst, PX = inst[~tiny], PX[~tiny]
            lods = lodmod.choose_lod(PX * 0.5)
            for lv in (0, 1, 2):
                sel = lods == lv
                if sel.any():
                    self._mesh(kind, lv).draw(inst[sel])

        # ---- glass shell (transparent, after particles so galaxies show through)
        if shell is not None:
            m.use()
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            sinst = _instances([[0, 0, 0]], [1.0], [[0, 0]], [0], [1], [(*rgb, scene.fade)], [0.5], [S_GLASS], [0], [0])
            self._device(shell[0], shell[1])[0].draw(sinst)
        self._draw_home_glass(scene, pos, col, item_draw, codes, hl)

        # ---- glows (additive billboards) --------------------------------------
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE)
        b = self.p_bill
        b.use()
        b.mat4("u_view", view)
        b.mat4("u_proj", proj)
        b.vec2("u_viewport", (width, height))
        b.vec3("u_cam_right", right)
        b.vec3("u_cam_up", up)
        b.f("u_time", t)
        b.f("u_alpha", 1.0)
        b.i("u_atlas", 0)
        if dots:
            d = np.concatenate(dots)
            dc = d[:, 8:12].copy()
            dc[:, :3] = np.clip(dc[:, :3] * 0.6 + 0.4, 0, 1)
            self.billboards.draw(_billboards(d[:, 0:3], d[:, 3] * 0.9, dc, (0, 0, 0, 0), 0))
        if glow_jobs:
            P = np.concatenate([g[0] for g in glow_jobs])
            S = np.concatenate([g[1] for g in glow_jobs])
            C = np.concatenate([g[2] for g in glow_jobs]).copy()
            # many overlapping additive glows would saturate to white
            C[:, 3] *= 0.85 * float(np.clip(18.0 / math.sqrt(max(len(P), 1)), 0.12, 1.0))
            self.billboards.draw(_billboards(P, S, C, (0, 0, 0, 0), 0))

        # ---- overlays: brackets, icons, reticles (no depth) ------------------
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        not_center = np.ones(len(scene), bool)
        not_center[0] = scene.payload is None  # the home scene has no centre item
        ov = vis & not_center & (alpha > 0.05)
        is_dir = scene.extra.get("_isdir")
        if is_dir is None or len(is_dir) != len(scene):
            is_dir = np.array([it.is_dir for it in scene.items], bool)
            scene.extra["_isdir"] = is_dir
        jobs = []
        bi = lodmod.top_k(px, ov & is_dir & (px > 3.0), lodmod.MAX_BRACKETS)
        if len(bi):
            bc = np.tile(mat.FOLDER_BRACKET_COLOR, (len(bi), 1)).astype(np.float32)
            bc[:, 3] *= alpha[bi] * np.clip(1.15 - px[bi] / 120.0, 0.25, 1.0)
            bs = px[bi] * 1.18 + 5.0
            jobs.append(_billboards(pos[bi], bs, bc, (0, 0, 0, 0), 12, extra=bs))
        ii = lodmod.top_k(px, ov & (px > lodmod.ICON_MIN_PX), lodmod.MAX_ICONS)
        if len(ii):
            uvs = np.array([self.atlas.uv_for(scene.items[i].icon_key or "file:?") for i in ii], np.float32)
            size = np.clip(px[ii] * 0.55, 9.0, 26.0)
            yoff = px[ii] + size + 3.0
            ic = np.ones((len(ii), 4), np.float32)
            ic[:, 3] = alpha[ii] * np.clip((px[ii] - 1.5) / 4.0, 0.3, 1.0)
            inst = _billboards(pos[ii], size, ic, (0, 0, 0, 0), 10, yoff)
            inst[:, 8:12] = uvs
            jobs.append(inst)
        for idx, color in ((hovered, mat.HOVER_COLOR), (selected, mat.SELECT_COLOR)):
            if idx is not None and 0 <= idx < len(scene) and vis[idx]:
                s = float(px[idx]) * 1.25 + 10.0
                jobs.append(_billboards(pos[idx:idx + 1], [s], [color], (0, 0, 0, 0), 11, extra=s))
        self.atlas.end_frame()
        if jobs:
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.atlas.tex)
            self.billboards.draw(np.concatenate(jobs))

        gl.glDepthMask(gl.GL_TRUE)
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        screen, _ = project(vp, pos, width, height)
        return FrameInfo(pos, rad, screen, px, vis & (alpha > 0.05), depth, width, height)

    # ---- helpers -------------------------------------------------------------
    def _background(self, view, proj, hue: float, t: float) -> None:
        rot = view.copy()
        rot[:3, 3] = 0
        inv = np.linalg.inv((proj @ rot).astype(np.float64))
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDisable(gl.GL_BLEND)
        self.p_bg.use()
        self.p_bg.mat4("u_inv_viewproj_rot", inv)
        self.p_bg.f("u_hue", hue)
        self.p_bg.f("u_alpha", 1.0)
        self.p_bg.f("u_time", t)
        gl.glBindVertexArray(self.bg_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glDepthMask(gl.GL_TRUE)

    def _lines(self, scene, pos, rad, col, spin, item_draw, codes, view, proj, alpha) -> None:
        lp = self.p_line
        lp.use()
        lp.mat4("u_view", view)
        lp.mat4("u_proj", proj)
        lp.f("u_alpha", 1.0)
        gl.glDepthMask(gl.GL_FALSE)
        rings = list(scene.orbit_rings)
        cols = [mat.ORBIT_COLOR] * len(rings)
        for a, b in scene.belts:
            rings += [a, b]
            cols += [mat.BELT_COLOR, mat.BELT_COLOR]
        if rings:
            n = len(rings)
            c = np.array(cols, np.float32)
            c[:, 3] *= scene.fade
            self.circle.draw(_instances(np.zeros((n, 3)), rings, np.zeros((n, 2)), np.zeros(n), np.ones(n), c,
                                        np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)))
        idx = np.nonzero(item_draw & scene.rings)[0]
        for code in np.unique(codes[idx]) if len(idx) else []:
            kind = self.kind_names[code]
            lm = self._line_mesh(kind)
            if lm is None:
                continue
            ii = idx[codes[idx] == code]
            c = col[ii].copy()
            c[:, :3] = np.clip(c[:, :3] * 1.2 + 0.1, 0, 1)
            c[:, 3] *= KINDS[kind].line_alpha
            lm.draw(_instances(pos[ii], rad[ii], scene.tilt[ii], spin[ii] * (0 if kind == "planet" else 1),
                               scene.squash[ii], c, scene.seed[ii], np.zeros(len(ii)), np.zeros(len(ii)), np.zeros(len(ii))))
        if scene.shell is not None:
            dkind, half, rgb = scene.shell
            edges = self._device(dkind, half)[2]
            edges.draw(_instances([[0, 0, 0]], [1.0], [[0, 0]], [0], [1], [(*rgb, 0.55 * scene.fade)],
                                  [0], [0], [0], [0]))
        # home view device edges
        for code in np.unique(codes[item_draw]) if item_draw.any() else []:
            kind = self.kind_names[code]
            if not kind.startswith("device:"):
                continue
            dk = kind[7:]
            ii = np.nonzero(item_draw & (codes == code))[0]
            scales = scene.extra.get("device_scale")
            edges = self._device(dk, default_half(dk))[2]
            c = col[ii].copy()
            c[:, 3] *= 0.7
            edges.draw(_instances(pos[ii], scales[ii], np.zeros((len(ii), 2)), np.zeros(len(ii)), np.ones(len(ii)),
                                  c, np.zeros(len(ii)), np.zeros(len(ii)), np.zeros(len(ii)), np.zeros(len(ii))))
        gl.glDepthMask(gl.GL_TRUE)

    def _draw_home_devices(self, scene, dkind, ii, pos, col, hl, t) -> None:
        """Opaque hardware details of the device-universes on the home screen."""
        scales = scene.extra.get("device_scale")
        dm = self._device(dkind, default_half(dkind))
        if len(ii) == 0:
            return
        n = len(ii)
        c = np.tile((*mat.DETAIL_COLOR, 1.0), (n, 1)).astype(np.float32)
        c[:, 3] = col[ii, 3]
        for dmesh, style in dm[1]:
            dmesh.draw(_instances(pos[ii], scales[ii], np.zeros((n, 2)), np.zeros(n), np.ones(n), c,
                                  np.zeros(n), np.full(n, style), hl[ii], np.zeros(n)))

    def _draw_home_glass(self, scene, pos, col, item_draw, codes, hl) -> None:
        if scene.payload is not None:
            return
        scales = scene.extra.get("device_scale")
        self.p_mesh.use()
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        for code in np.unique(codes[item_draw]) if item_draw.any() else []:
            kind = self.kind_names[code]
            if not kind.startswith("device:"):
                continue
            dk = kind[7:]
            ii = np.nonzero(item_draw & (codes == code))[0]
            n = len(ii)
            shell = self._device(dk, default_half(dk))[0]
            shell.draw(_instances(pos[ii], scales[ii], np.zeros((n, 2)), np.zeros(n), np.ones(n), col[ii],
                                  scene.seed[ii], np.full(n, S_GLASS), hl[ii], np.zeros(n)))
