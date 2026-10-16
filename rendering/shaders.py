"""GLSL 3.30 core shaders."""

NOISE = """
float hash13(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.zyx + 31.32);
    return fract((p.x + p.y) * p.z);
}
float vnoise(vec3 x) {
    vec3 i = floor(x); vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash13(i + vec3(0,0,0)), hash13(i + vec3(1,0,0)), f.x),
                   mix(hash13(i + vec3(0,1,0)), hash13(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash13(i + vec3(0,0,1)), hash13(i + vec3(1,0,1)), f.x),
                   mix(hash13(i + vec3(0,1,1)), hash13(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float fbm(vec3 p) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 5; i++) { s += a * vnoise(p); p = p * 2.03 + vec3(1.7, 9.2, 3.1); a *= 0.5; }
    return s;
}
float fbm3(vec3 p) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 3; i++) { s += a * vnoise(p); p = p * 2.1 + vec3(4.1, 1.3, 7.7); a *= 0.5; }
    return s / 0.875;
}
"""

INSTANCE_ROT = """
mat3 rotX(float a) { float c = cos(a), s = sin(a); return mat3(1,0,0, 0,c,s, 0,-s,c); }
mat3 rotY(float a) { float c = cos(a), s = sin(a); return mat3(c,0,-s, 0,1,0, s,0,c); }
mat3 rotZ(float a) { float c = cos(a), s = sin(a); return mat3(c,s,0, -s,c,0, 0,0,1); }
"""

MESH_VS = """#version 330 core
layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_nrm;
layout(location=2) in vec2 a_uv;
layout(location=3) in vec4 i_pos;   // xyz, uniform scale
layout(location=4) in vec4 i_rot;   // tilt x, tilt z, spin, y-squash
layout(location=5) in vec4 i_col;
layout(location=6) in vec4 i_par;   // seed, style, highlight, emissive
uniform mat4 u_view;
uniform mat4 u_proj;
out vec3 v_wpos; out vec3 v_nrm; out vec3 v_opos; out vec2 v_uv; out vec4 v_col; out vec4 v_par;
""" + INSTANCE_ROT + """
void main() {
    mat3 R = rotZ(i_rot.y) * rotX(i_rot.x) * rotY(i_rot.z);
    // negative squash = "conform to a sphere of that radius" (craters on moons)
    float conform = i_rot.w < 0.0 ? -i_rot.w : 0.0;
    vec3 sq = vec3(1.0, conform > 0.0 ? 1.0 : i_rot.w, 1.0);
    vec3 w = R * (a_pos * sq * i_pos.w) + i_pos.xyz;
    if (conform > 0.0) {
        vec3 flatp = R * (vec3(a_pos.x, 0.0, a_pos.z) * i_pos.w) + i_pos.xyz;
        float h = max(a_pos.y, 0.0) * i_pos.w + 0.022 * conform;   // clear the moon's relief
        w = normalize(flatp) * (conform + h);
    }
    v_wpos = w;
    v_nrm = R * normalize(a_nrm / sq);
    v_opos = a_pos;
    v_uv = a_uv;
    v_col = i_col;
    v_par = i_par;
    gl_Position = u_proj * u_view * vec4(w, 1.0);
}
"""

MESH_FS = """#version 330 core
in vec3 v_wpos; in vec3 v_nrm; in vec3 v_opos; in vec2 v_uv; in vec4 v_col; in vec4 v_par;
uniform vec3 u_eye;
uniform vec3 u_light_pos;
uniform int u_star_light;
uniform float u_time;
uniform float u_alpha;
uniform sampler2D u_tex;
out vec4 frag;
""" + NOISE + """
float craters(vec3 p, out float rimv) {
    vec3 q = p * 3.0; vec3 i = floor(q); vec3 f = fract(q);
    float best = 1e9; float rad = 0.4;
    for (int x = -1; x <= 1; x++) for (int y = -1; y <= 1; y++) for (int z = -1; z <= 1; z++) {
        vec3 g = vec3(x, y, z);
        vec3 o = vec3(hash13(i + g), hash13(i + g + 17.0), hash13(i + g + 41.0));
        float d = length(g + o - f);
        if (d < best) { best = d; rad = 0.18 + 0.3 * hash13(i + g + 77.0); }
    }
    float inside = 1.0 - smoothstep(rad * 0.75, rad, best);
    rimv = smoothstep(rad * 0.7, rad, best) * (1.0 - smoothstep(rad, rad * 1.25, best));
    return inside;
}
void main() {
    vec3 N = normalize(v_nrm);
    if (!gl_FrontFacing) N = -N;
    vec3 V = normalize(u_eye - v_wpos);
    vec3 L = (u_star_light == 1) ? normalize(u_light_pos - v_wpos) : normalize(vec3(0.55, 0.75, 0.35));
    float seed = v_par.x;
    int style = int(v_par.y + 0.5);
    float hl = v_par.z;
    float emis = v_par.w;
    vec3 base = v_col.rgb;
    float alpha = v_col.a;
    vec3 so = normalize(v_opos + 1e-5);
    vec3 p = v_opos * 1.6 + vec3(seed * 37.0, seed * 11.0, seed * 23.0);
    vec3 col = base;
    vec3 emissive = vec3(0.0);
    float spec_k = 0.15, rough = 24.0, rim_atmo = 0.0, ambient = (u_star_light == 1) ? 0.10 : 0.22;
    bool unlit = false;
    if (style == 0) {                         // terrestrial planet
        float h = fbm(p * 1.2);
        float sea = 0.47 + 0.12 * (fract(seed * 7.0) - 0.5);
        vec3 deep = base * 0.18 + vec3(0.0, 0.03, 0.12);
        vec3 shallow = base * 0.45 + vec3(0.02, 0.12, 0.25);
        vec3 land = mix(base, vec3(0.35, 0.42, 0.18), 0.45);
        vec3 high = mix(base, vec3(0.55, 0.45, 0.35), 0.6);
        if (h < sea) { col = mix(deep, shallow, h / sea); spec_k = 0.7; rough = 60.0; }
        else { col = mix(land, high, smoothstep(sea, 0.75, h)); spec_k = 0.04; }
        float ice = smoothstep(0.80, 0.9, abs(so.y) + (h - 0.5) * 0.3);
        col = mix(col, vec3(0.93, 0.96, 1.0), ice);
        float cl = smoothstep(0.52, 0.72, fbm3(p * 2.2 + vec3(u_time * 0.015, 0.0, u_time * 0.01)));
        col = mix(col, vec3(1.0), cl * 0.7);
        rim_atmo = 1.0;
    } else if (style == 1) {                  // gas giant
        float turb = fbm(p * vec3(1.0, 5.0, 1.0)) * 2.2;
        float band = sin(so.y * (9.0 + seed * 16.0) + turb);
        vec3 c2 = base * vec3(1.15, 0.85, 0.65) + 0.08;
        col = mix(base * 0.7, c2, band * 0.5 + 0.5);
        vec3 spot = vec3(0.6, 0.15, 0.1) + base * 0.3;
        float sd = length(vec2(atan(so.z, so.x) - seed * 6.0, (so.y - (seed - 0.5)) * 3.0));
        col = mix(col, spot, (1.0 - smoothstep(0.15, 0.3, sd)) * 0.7);
        rim_atmo = 0.7; spec_k = 0.08;
    } else if (style == 2) {                  // moon
        float rimv;
        float c = craters(p, rimv);
        float c2r; float c2 = craters(p * 2.3 + 5.0, c2r);
        float maria = smoothstep(0.42, 0.55, fbm3(p * 0.7));
        col = base * (0.62 + 0.5 * fbm(p * 4.0));
        col *= 1.0 - 0.35 * maria;
        col *= 1.0 - 0.25 * c - 0.15 * c2;
        col += base * (0.35 * rimv + 0.2 * c2r);
        spec_k = 0.03;
    } else if (style == 3 || style == 10) {   // rock / crater terrain
        float f = fbm(v_opos * 4.0 + seed * 10.0);
        col = base * (0.5 + 0.7 * f);
        col *= 0.9 + 0.1 * sin(v_opos.y * 40.0 + f * 6.0);
        if (style == 10) {
            float r = length(v_opos.xz);
            col *= 0.75 + 0.35 * smoothstep(0.6, 1.0, r);     // darker floor, bright rim
            float ej = fbm3(vec3(atan(v_opos.z, v_opos.x) * 6.0, r * 3.0, seed));
            col += base * 0.25 * smoothstep(1.0, 1.1, r) * ej;
        }
        spec_k = 0.05;
    } else if (style == 4) {                  // sand grain (quartz)
        col = base * (0.85 + 0.3 * hash13(floor(v_opos * 9.0 + seed * 50.0)));
        spec_k = 0.9; rough = 90.0;
        alpha *= 0.95;
    } else if (style == 5) {                  // star
        float g = fbm(p * 3.0 + vec3(u_time * 0.12));
        float spots = smoothstep(0.62, 0.7, fbm3(p * 1.5 + 3.0));
        float limb = 0.55 + 0.45 * max(dot(N, V), 0.0);
        col = base * (1.15 + 0.9 * g) * limb * (1.0 - 0.4 * spots) + vec3(0.25) * limb;
        unlit = true;
    } else if (style == 6) {                  // crystal (file objects)
        float fres = pow(1.0 - max(dot(N, V), 0.0), 2.0);
        col = base * 0.55;
        emissive = base * (0.35 + 0.25 * sin(u_time * 1.7 + seed * 30.0)) + base * fres * 0.8;
        spec_k = 1.0; rough = 80.0; alpha *= 0.94;
    } else if (style == 7) {                  // microbe / cell
        float fres = pow(1.0 - max(dot(N, V), 0.0), 2.0);
        float org = smoothstep(0.55, 0.7, fbm(p * 3.0 + vec3(0.0, u_time * 0.05, 0.0)));
        col = base * (0.35 + 0.5 * org);
        emissive = base * fres * 0.9;
        alpha *= 0.55 + 0.45 * fres;
        spec_k = 0.5;
    } else if (style == 9) {                  // device glass shell
        float fres = pow(1.0 - abs(dot(N, V)), 3.0);
        vec2 g = abs(fract(v_wpos.xz * 0.25) - 0.5);
        float grid = smoothstep(0.47, 0.5, max(g.x, g.y));
        vec2 g2 = abs(fract(v_wpos.xz * 1.0 + 0.5) - 0.5);
        float trace = smoothstep(0.485, 0.5, max(g2.x, g2.y)) * step(0.6, hash13(floor(v_wpos * 1.0)));
        col = base * 0.2;
        emissive = base * (fres * 0.7 + grid * 0.18 + trace * 0.12);
        alpha = (0.05 + 0.5 * fres + grid * 0.1) * v_col.a;
        spec_k = 0.6; rough = 64.0;
    } else if (style == 11) {                 // metal / gold contacts
        col = base * 0.75; spec_k = 1.0; rough = 70.0; ambient += 0.1;
    } else if (style == 12) {                 // image texture (preview planets)
        col = texture(u_tex, vec2(v_uv.x, v_uv.y)).rgb;
        rim_atmo = 0.5; ambient = 0.35;
    } else if (style == 13) {                 // energy (quantum)
        float w = 0.5 + 0.5 * sin(u_time * 3.0 + v_opos.y * 10.0 + seed * 20.0);
        col = base * 0.3; emissive = base * (0.6 + 0.9 * w);
    } else if (style == 14) {                 // chip package
        col = vec3(0.07, 0.08, 0.09) + base * 0.05;
        spec_k = 0.4; rough = 40.0;
    } else {                                  // glossy plain
        col = base * (0.85 + 0.15 * vnoise(p * 4.0)); spec_k = 0.55; rough = 48.0;
    }
    vec3 color;
    float ndv = max(dot(N, V), 0.0);
    if (unlit) {
        color = col;
    } else {
        float diff = max(dot(N, L), 0.0);
        vec3 H = normalize(L + V);
        float spec = pow(max(dot(N, H), 0.0), rough) * spec_k;
        color = col * (ambient + diff * 0.95) + vec3(spec);
        float rim = pow(1.0 - ndv, 3.0) * rim_atmo;
        color += (base * 0.4 + vec3(0.25, 0.45, 1.0) * 0.6) * rim * (0.25 + diff);
    }
    color += emissive + base * emis * 0.15;
    color += vec3(0.3, 0.7, 1.0) * hl * (0.06 + pow(1.0 - ndv, 2.0) * 1.0);
    frag = vec4(color, clamp(alpha * u_alpha, 0.0, 1.0));
}
"""

LINE_VS = """#version 330 core
layout(location=0) in vec3 a_pos;
layout(location=3) in vec4 i_pos;
layout(location=4) in vec4 i_rot;
layout(location=5) in vec4 i_col;
uniform mat4 u_view; uniform mat4 u_proj;
out vec4 v_col;
""" + INSTANCE_ROT + """
void main() {
    mat3 R = rotZ(i_rot.y) * rotX(i_rot.x) * rotY(i_rot.z);
    vec3 w = R * (a_pos * vec3(1.0, i_rot.w, 1.0) * i_pos.w) + i_pos.xyz;
    v_col = i_col;
    gl_Position = u_proj * u_view * vec4(w, 1.0);
}
"""

LINE_FS = """#version 330 core
in vec4 v_col;
uniform float u_alpha;
out vec4 frag;
void main() { frag = vec4(v_col.rgb, v_col.a * u_alpha); }
"""

POINTS_VS = """#version 330 core
layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_col;
layout(location=2) in vec2 a_sz;    // size (object units), brightness
layout(location=3) in vec4 i_pos;
layout(location=4) in vec4 i_rot;
layout(location=5) in vec4 i_col;
layout(location=6) in vec4 i_par;
uniform mat4 u_view; uniform mat4 u_proj;
uniform float u_px_scale;            // viewport_h / (2 tan(fov/2))
out vec4 v_col;
""" + INSTANCE_ROT + """
void main() {
    mat3 R = rotZ(i_rot.y) * rotX(i_rot.x) * rotY(i_rot.z);
    vec3 w = R * (a_pos * i_pos.w) + i_pos.xyz;
    vec4 vp = u_view * vec4(w, 1.0);
    gl_Position = u_proj * vp;
    float px = a_sz.x * i_pos.w * u_px_scale / max(-vp.z, 1e-4);
    float fade = clamp(px / 1.5, 0.0, 1.0);
    gl_PointSize = clamp(px, 1.5, 48.0);
    vec3 tint = mix(vec3(1.0), i_col.rgb, 0.55);
    v_col = vec4(a_col * tint * (1.0 + i_par.z * 0.8), a_sz.y * i_col.a * (0.35 + 0.65 * fade));
}
"""

POINTS_FS = """#version 330 core
in vec4 v_col;
uniform float u_alpha;
out vec4 frag;
void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    float d = dot(c, c);
    if (d > 1.0) discard;
    float a = exp(-d * 3.5);
    frag = vec4(v_col.rgb * a, a * v_col.a * u_alpha);
}
"""

BILLBOARD_VS = """#version 330 core
layout(location=0) in vec2 a_corner;
layout(location=1) in vec4 i_pos;   // xyz, size (world units, or pixels for modes >= 10)
layout(location=2) in vec4 i_col;
layout(location=3) in vec4 i_uv;    // atlas rect
layout(location=4) in vec4 i_par;   // mode, pixel y offset, rotation, extra
uniform mat4 u_view; uniform mat4 u_proj;
uniform vec2 u_viewport;
uniform vec3 u_cam_right; uniform vec3 u_cam_up;
out vec2 v_c; out vec2 v_uv; out vec4 v_col; flat out int v_mode; out float v_extra;
void main() {
    int mode = int(i_par.x + 0.5);
    v_c = a_corner; v_col = i_col; v_mode = mode; v_extra = i_par.w;
    vec2 t = a_corner * 0.5 + 0.5;
    v_uv = vec2(mix(i_uv.x, i_uv.z, t.x), mix(i_uv.w, i_uv.y, t.y));
    float c = cos(i_par.z), s = sin(i_par.z);
    vec2 rc = vec2(c * a_corner.x - s * a_corner.y, s * a_corner.x + c * a_corner.y);
    if (mode >= 10) {
        vec4 clip = u_proj * u_view * vec4(i_pos.xyz, 1.0);
        if (clip.w <= 0.0) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
        vec2 off = (rc * i_pos.w + vec2(0.0, i_par.y)) * 2.0 / u_viewport;
        clip.xy += off * clip.w;
        clip.z = 0.0;
        gl_Position = clip;
    } else {
        vec3 w = i_pos.xyz + (u_cam_right * rc.x + u_cam_up * rc.y) * i_pos.w;
        gl_Position = u_proj * u_view * vec4(w, 1.0);
    }
}
"""

BILLBOARD_FS = """#version 330 core
in vec2 v_c; in vec2 v_uv; in vec4 v_col; flat in int v_mode; in float v_extra;
uniform sampler2D u_atlas;
uniform float u_time;
uniform float u_alpha;
out vec4 frag;
void main() {
    float d = length(v_c);
    if (v_mode == 0) {                      // corona glow (additive)
        float a = exp(-d * d * 4.0) * 0.8 + exp(-d * d * 30.0) * 0.7;
        float ang = atan(v_c.y, v_c.x);
        a += 0.18 * exp(-d * 3.0) * pow(abs(cos(ang * 2.0)), 40.0);
        a *= 1.0 - smoothstep(0.85, 1.0, d);
        frag = vec4(v_col.rgb * a * v_col.a * u_alpha, 1.0);
    } else if (v_mode == 1) {               // soft halo ring (world)
        float ring = smoothstep(0.80, 0.92, d) * (1.0 - smoothstep(0.92, 1.0, d));
        frag = vec4(v_col.rgb, ring * v_col.a * u_alpha);
    } else if (v_mode == 10) {              // icon from atlas
        vec4 t = texture(u_atlas, v_uv);
        frag = vec4(t.rgb, t.a * v_col.a * u_alpha);
    } else if (v_mode == 11) {              // selection reticle (pixels)
        float w = 1.5 / max(v_extra, 8.0);
        float ring = smoothstep(1.0 - 3.0 * w, 1.0 - 2.0 * w, d) * (1.0 - smoothstep(1.0 - w, 1.0, d));
        float ang = atan(v_c.y, v_c.x) + u_time * 1.2;
        float dash = step(0.35, fract(ang * 6.0 / 6.2831853));
        float inner = smoothstep(0.80, 0.84, d) * (1.0 - smoothstep(0.86, 0.9, d)) * 0.35;
        frag = vec4(v_col.rgb, (ring * dash + inner) * v_col.a * u_alpha);
    } else if (v_mode == 12) {              // folder corner brackets (pixels)
        vec2 a = abs(v_c);
        float w = 2.0 / max(v_extra, 8.0);
        float edge = max(step(1.0 - w, a.x), step(1.0 - w, a.y));
        float corner = step(0.62, a.x) * step(0.62, a.y);
        frag = vec4(v_col.rgb, edge * corner * v_col.a * u_alpha);
    } else {                                // dot marker
        float a = 1.0 - smoothstep(0.5, 1.0, d);
        frag = vec4(v_col.rgb, a * v_col.a * u_alpha);
    }
}
"""

BACKGROUND_VS = """#version 330 core
out vec2 v_ndc;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2) * 2.0 - 1.0;
    v_ndc = p;
    gl_Position = vec4(p, 0.9999, 1.0);
}
"""

BACKGROUND_FS = """#version 330 core
in vec2 v_ndc;
uniform mat4 u_inv_viewproj_rot;
uniform float u_hue;
uniform float u_alpha;
uniform float u_time;
out vec4 frag;
""" + NOISE + """
vec3 hue2rgb(float h) {
    vec3 k = clamp(abs(fract(h + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
    return k;
}
void main() {
    vec4 w = u_inv_viewproj_rot * vec4(v_ndc, 1.0, 1.0);
    vec3 dir = normalize(w.xyz / w.w);
    float n1 = fbm(dir * 2.2 + vec3(u_hue * 10.0));
    float n2 = fbm3(dir * 4.5 + vec3(3.0, u_hue * 5.0, 1.0));
    vec3 c1 = hue2rgb(u_hue) * 0.55 + 0.05;
    vec3 c2 = hue2rgb(u_hue + 0.33) * 0.45;
    vec3 col = vec3(0.004, 0.006, 0.016);
    float neb = pow(smoothstep(0.35, 0.85, n1), 2.0);
    col += c1 * neb * 0.35 + c2 * pow(smoothstep(0.4, 0.9, n2), 3.0) * 0.25 * (0.4 + neb);
    float dust = smoothstep(0.55, 0.75, fbm3(dir * 6.0 + 9.0));
    col *= 1.0 - dust * 0.5;
    // stars on several cell scales
    for (int i = 0; i < 3; i++) {
        float sc = 120.0 + float(i) * 170.0;
        vec3 q = dir * sc;
        vec3 cell = floor(q);
        float h = hash13(cell + float(i) * 13.0);
        if (h > 0.985) {
            vec3 o = vec3(hash13(cell + 1.0), hash13(cell + 2.0), hash13(cell + 3.0));
            float d = length(fract(q) - o);
            float tw = 0.75 + 0.25 * sin(u_time * (1.0 + h * 3.0) + h * 40.0);
            float b = smoothstep(0.12, 0.0, d) * (h - 0.985) / 0.015 * tw;
            col += mix(vec3(0.7, 0.8, 1.0), vec3(1.0, 0.85, 0.7), hash13(cell + 5.0)) * b * 1.6;
        }
    }
    frag = vec4(col * u_alpha, 1.0);
}
"""
