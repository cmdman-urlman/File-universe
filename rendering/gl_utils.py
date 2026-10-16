"""Thin OpenGL 3.3 core wrappers (programs, instanced meshes, billboards)."""
from __future__ import annotations

import ctypes

import numpy as np
from OpenGL import GL as gl

from objects.geometry import LINES, POINTS, MeshData

FLOAT = 4
INSTANCE_FLOATS = 16


class ShaderError(RuntimeError):
    pass


def _compile(src: str, kind) -> int:
    sh = gl.glCreateShader(kind)
    gl.glShaderSource(sh, src)
    gl.glCompileShader(sh)
    if gl.glGetShaderiv(sh, gl.GL_COMPILE_STATUS) != gl.GL_TRUE:
        log = gl.glGetShaderInfoLog(sh)
        raise ShaderError(log.decode() if isinstance(log, bytes) else str(log))
    return sh


class ShaderProgram:
    def __init__(self, vs: str, fs: str):
        v = _compile(vs, gl.GL_VERTEX_SHADER)
        f = _compile(fs, gl.GL_FRAGMENT_SHADER)
        self.id = gl.glCreateProgram()
        gl.glAttachShader(self.id, v)
        gl.glAttachShader(self.id, f)
        gl.glLinkProgram(self.id)
        if gl.glGetProgramiv(self.id, gl.GL_LINK_STATUS) != gl.GL_TRUE:
            log = gl.glGetProgramInfoLog(self.id)
            raise ShaderError(log.decode() if isinstance(log, bytes) else str(log))
        gl.glDeleteShader(v)
        gl.glDeleteShader(f)
        self._loc: dict[str, int] = {}

    def use(self) -> None:
        gl.glUseProgram(self.id)

    def loc(self, name: str) -> int:
        l = self._loc.get(name)
        if l is None:
            l = gl.glGetUniformLocation(self.id, name)
            self._loc[name] = l
        return l

    def mat4(self, name: str, m: np.ndarray) -> None:
        gl.glUniformMatrix4fv(self.loc(name), 1, gl.GL_TRUE, np.ascontiguousarray(m, np.float32))

    def vec3(self, name: str, v) -> None:
        gl.glUniform3f(self.loc(name), float(v[0]), float(v[1]), float(v[2]))

    def vec2(self, name: str, v) -> None:
        gl.glUniform2f(self.loc(name), float(v[0]), float(v[1]))

    def f(self, name: str, v: float) -> None:
        gl.glUniform1f(self.loc(name), float(v))

    def i(self, name: str, v: int) -> None:
        gl.glUniform1i(self.loc(name), int(v))


def _attrib(index: int, size: int, stride: int, offset: int, divisor: int = 0) -> None:
    gl.glEnableVertexAttribArray(index)
    gl.glVertexAttribPointer(index, size, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(offset))
    if divisor:
        gl.glVertexAttribDivisor(index, divisor)


class GPUMesh:
    """A mesh in GPU memory with its own instance buffer (attributes 3..6)."""

    def __init__(self, data: MeshData):
        self.mode = {POINTS: gl.GL_POINTS, LINES: gl.GL_LINES}.get(data.mode, gl.GL_TRIANGLES)
        verts = data.vertex_array()
        self.vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(self.vao)
        self.vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts, gl.GL_STATIC_DRAW)
        stride = 8 * FLOAT
        _attrib(0, 3, stride, 0)
        _attrib(1, 3, stride, 3 * FLOAT)
        _attrib(2, 2, stride, 6 * FLOAT)
        self.ebo = None
        if data.indices is not None and data.mode != POINTS:
            idx = np.ascontiguousarray(data.indices, np.uint32)
            self.ebo = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.ebo)
            gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, gl.GL_STATIC_DRAW)
            self.count = len(idx)
        else:
            self.count = len(verts)
        self.ibo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.ibo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, INSTANCE_FLOATS * FLOAT, None, gl.GL_DYNAMIC_DRAW)
        istride = INSTANCE_FLOATS * FLOAT
        for k in range(4):
            _attrib(3 + k, 4, istride, 4 * k * FLOAT, divisor=1)
        self._icap = 1
        gl.glBindVertexArray(0)

    def draw(self, instances: np.ndarray) -> None:
        n = len(instances)
        if n == 0:
            return
        data = np.ascontiguousarray(instances, np.float32)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.ibo)
        if n > self._icap:
            self._icap = max(n, self._icap * 2)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, self._icap * INSTANCE_FLOATS * FLOAT, None, gl.GL_DYNAMIC_DRAW)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, data.nbytes, data)
        if self.ebo is not None:
            gl.glDrawElementsInstanced(self.mode, self.count, gl.GL_UNSIGNED_INT, ctypes.c_void_p(0), n)
        else:
            gl.glDrawArraysInstanced(self.mode, 0, self.count, n)

    def delete(self) -> None:
        bufs = [b for b in (self.vbo, self.ebo, self.ibo) if b]
        gl.glDeleteBuffers(len(bufs), bufs)
        gl.glDeleteVertexArrays(1, [self.vao])


class BillboardBatch:
    """Instanced camera-facing quads: pos4, col4, uv4, par4 per instance."""

    def __init__(self):
        corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, -1], [1, 1], [-1, 1]], np.float32)
        self.vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(self.vao)
        self.vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, corners.nbytes, corners, gl.GL_STATIC_DRAW)
        _attrib(0, 2, 2 * FLOAT, 0)
        self.ibo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.ibo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, 16 * FLOAT, None, gl.GL_DYNAMIC_DRAW)
        for k in range(4):
            _attrib(1 + k, 4, 16 * FLOAT, 4 * k * FLOAT, divisor=1)
        self._icap = 1
        gl.glBindVertexArray(0)

    def draw(self, instances: np.ndarray) -> None:
        n = len(instances)
        if n == 0:
            return
        data = np.ascontiguousarray(instances, np.float32)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.ibo)
        if n > self._icap:
            self._icap = max(n, self._icap * 2)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, self._icap * 16 * FLOAT, None, gl.GL_DYNAMIC_DRAW)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, data.nbytes, data)
        gl.glDrawArraysInstanced(gl.GL_TRIANGLES, 0, 6, n)


def create_texture_rgba(width: int, height: int, data: bytes | None = None, mipmap: bool = True) -> int:
    tex = gl.glGenTextures(1)
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                       gl.GL_LINEAR_MIPMAP_LINEAR if mipmap else gl.GL_LINEAR)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
    gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, width, height, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data)
    if mipmap and data is not None:
        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
    return int(tex)
