(() => {
  const radius = bytes => 0.12 * Math.pow(1.32, Math.log10(bytes));
  const css = getComputedStyle(document.documentElement);
  const tok = n => css.getPropertyValue(n).trim();

  /* ---- size scale, drawn with the real formula ---- */
  const svg = document.getElementById("scale-svg");
  const marks = [["1 KB", 1e3], ["1 MB", 1e6], ["100 MB", 1e8], ["1 GB", 1e9], ["100 GB", 1e11], ["1 TB", 1e12]];
  const unit = 30;                                // px per world unit
  const base = 170;                               // circles sit on this line
  let x = 20, out = "";
  out += `<line x1="0" y1="${base}" x2="600" y2="${base}" stroke="${tok("--line")}" stroke-width="1"/>`;
  for (const [label, b] of marks) {
    const r = radius(b) * unit;
    x += r;
    out += `<circle cx="${x.toFixed(1)}" cy="${(base - r).toFixed(1)}" r="${r.toFixed(1)}" fill="${tok("--star")}" fill-opacity="${(0.25 + r / 200).toFixed(2)}" stroke="${tok("--star")}" stroke-width="1.2"/>`;
    out += `<text x="${x.toFixed(1)}" y="${base + 26}" text-anchor="middle" fill="${tok("--ink")}" font-family="IBM Plex Mono, monospace" font-size="13">${label}</text>`;
    out += `<text x="${x.toFixed(1)}" y="${base + 46}" text-anchor="middle" fill="${tok("--dim")}" font-family="IBM Plex Mono, monospace" font-size="12">${radius(b).toFixed(2)}</text>`;
    x += r + 18;
  }
  out += `<text x="0" y="${base + 76}" fill="${tok("--dim")}" font-family="IBM Plex Mono, monospace" font-size="11">radius in world units, drawn to scale</text>`;
  svg.innerHTML = out;

  /* ---- hero galaxy ---- */
  const cv = document.getElementById("galaxy");
  const ctx = cv.getContext("2d");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  // sample C:\Users\you style folders with plausible sizes; sizes drive the star radius
  const folders = [
    ["AppData", 38e9], ["Documents", 6.2e9], ["Pictures", 84e9], ["Videos", 210e9],
    ["Downloads", 17e9], ["Music", 22e9], ["Desktop", 1.4e9], ["source", 9.8e9], ["OneDrive", 54e9],
  ];
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const ARMS = 3, stars = [];
  for (let i = 0; i < 1500; i++) {
    const arm = i % ARMS, t = Math.pow(rnd(), 0.7);
    const ang = arm * (Math.PI * 2 / ARMS) + t * 4.4 + (rnd() - 0.5) * 0.55;
    const d = 0.08 + t * 0.92;
    stars.push({ a: ang, d, z: (rnd() - 0.5) * 0.06 * (1.2 - t), s: rnd() * 1.3 + 0.3, warm: rnd() < 0.35, tw: rnd() * 6.28 });
  }
  const named = folders.map(([name, size], i) => ({
    name, size, a: (i % ARMS) * (Math.PI * 2 / ARMS) + (0.3 + (i / folders.length) * 0.75) * 4.4,
    d: 0.3 + (i / folders.length) * 0.62, r: radius(size),
  }));
  const fmt = b => b >= 1e9 ? (b / 1e9).toFixed(b >= 1e11 ? 0 : 1) + " GB" : (b / 1e6).toFixed(0) + " MB";

  let W = 0, H = 0, dpr = 1;
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = cv.getBoundingClientRect();
    W = r.width; H = r.height;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  const tilt = 0.42;
  function project(a, d, z, rot, R) {
    const x = Math.cos(a + rot) * d, y = Math.sin(a + rot) * d;
    return [W / 2 + x * R, H / 2 + (y * tilt + z) * R];
  }
  function frame(time) {
    const rot = reduce ? 0.6 : time * 0.00004;
    const R = Math.min(W, H * 1.6) * 0.47;
    ctx.clearRect(0, 0, W, H);
    // core glow
    const g = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, R * 0.42);
    g.addColorStop(0, "rgba(255,226,170,0.85)"); g.addColorStop(0.25, "rgba(255,190,120,0.28)"); g.addColorStop(1, "rgba(80,110,220,0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(W / 2, H / 2, R * 0.42, R * 0.42 * tilt * 1.4, 0, 0, Math.PI * 2); ctx.fill();
    for (const s of stars) {
      const [px, py] = project(s.a, s.d, s.z, rot, R);
      const tw = reduce ? 1 : 0.75 + 0.25 * Math.sin(time * 0.002 + s.tw);
      ctx.fillStyle = s.warm ? `rgba(255,212,138,${0.75 * tw})` : `rgba(160,200,255,${0.6 * tw})`;
      ctx.fillRect(px, py, s.s, s.s);
    }
    // labelled folder stars with the app's cyan corner brackets
    ctx.font = "500 11px 'IBM Plex Mono', Consolas, monospace";
    ctx.textBaseline = "middle";
    const folder = tok("--folder");
    for (const f of named) {
      const [px, py] = project(f.a, f.d, 0, rot, R);
      const pr = f.r * 3.2;
      const halo = ctx.createRadialGradient(px, py, 0, px, py, pr * 2.4);
      halo.addColorStop(0, "rgba(255,240,210,1)"); halo.addColorStop(0.35, "rgba(255,212,138,0.55)"); halo.addColorStop(1, "rgba(255,212,138,0)");
      ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(px, py, pr * 2.4, 0, Math.PI * 2); ctx.fill();
      const b = pr + 6, k = 4;
      ctx.strokeStyle = folder; ctx.lineWidth = 1.2; ctx.beginPath();
      for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
        ctx.moveTo(px + sx * b, py + sy * (b - k)); ctx.lineTo(px + sx * b, py + sy * b); ctx.lineTo(px + sx * (b - k), py + sy * b);
      }
      ctx.stroke();
      if (W > 300) {
        ctx.fillStyle = folder; ctx.fillText(f.name, px + b + 6, py - 6);
        ctx.fillStyle = tok("--dim"); ctx.fillText(fmt(f.size), px + b + 6, py + 7);
      }
    }
    if (!reduce) requestAnimationFrame(frame);
  }
  resize();
  addEventListener("resize", () => { resize(); if (reduce) frame(0); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => reduce && frame(0));
  reduce ? frame(0) : requestAnimationFrame(frame);

  /* ---- copy setup commands ---- */
  const btn = document.getElementById("copy-btn");
  btn.addEventListener("click", () => {
    const text = "py -m pip install -r requirements.txt\npy main.py";
    const done = () => { btn.textContent = "Copied"; setTimeout(() => (btn.textContent = "Copy"), 1600); };
    const fallback = () => { const sel = getSelection(), r = document.createRange(); r.selectNodeContents(document.getElementById("cmds")); sel.removeAllRanges(); sel.addRange(r); btn.textContent = "Press Ctrl+C"; };
    try { navigator.clipboard.writeText(text).then(done, fallback); } catch (e) { fallback(); }
  });
})();
