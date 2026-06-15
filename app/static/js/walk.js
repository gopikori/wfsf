/* Walk preview animation.
 *
 * Reads #walk-data and animates a marker through the day's stops.
 *  - SIT: marker holds at a stop (~1.4s — gives the user time to read it)
 *  - HOP: marker eases between stops (~1.0s) along a straight line
 *  - Floor change: crossfades the floor image at the midpoint of the hop
 *
 * SVG overlay uses viewBox 0-100 on both axes with preserveAspectRatio="none",
 * so a stop's (x_pct, y_pct) maps 1:1 to viewBox coords. The marker transform
 * is owned exclusively by JS via setAttribute('transform', ...) — no CSS
 * transform on .walk-marker (SVG2 lets CSS transform override the SVG attr,
 * which silently pins the dot to its CSS position).
 *
 * Per-floor we ALSO render: small pins at every stop on that floor, dashed
 * line connecting them in time order, and a faint label at every room on
 * the floor (regardless of whether it's a pick) so the user can ground
 * themselves on the plan.
 */
(function () {
  const data = (() => {
    const tag = document.getElementById('walk-data');
    if (!tag) return null;
    try { return JSON.parse(tag.textContent || '{}'); } catch (_) { return null; }
  })();
  if (!data || !Array.isArray(data.hops) || !data.hops.length) return;

  const stage = document.getElementById('walk-stage');
  const overlay = document.getElementById('walk-overlay');
  const marker = document.getElementById('walk-marker');
  const trail = document.getElementById('walk-trail');
  const pinsGroup = document.getElementById('walk-pins');
  const labelsGroup = document.getElementById('walk-labels');
  const playBtn = document.getElementById('walk-play');
  const scrub = document.getElementById('walk-scrub');
  const rewind = document.getElementById('walk-rewind');
  const floorLabel = document.getElementById('walk-floor-label');
  const wcEyebrow = document.getElementById('wc-eyebrow');
  const wcTitle = document.getElementById('wc-title');
  const wcMeta = document.getElementById('wc-meta');
  const stops = Array.from(document.querySelectorAll('.walk-stop'));
  const floorImgs = Array.from(document.querySelectorAll('.walk-floor'));
  if (!stage || !overlay || !marker || !playBtn || !scrub) return;

  const SIT_MS = 1400;
  const HOP_MS = 1000;

  /* Build a timeline of segments. Off-venue stops (no coords) stay at the
     previous on-venue position so the marker doesn't snap to (0,0). */
  const segments = [];
  let cursor = 0;
  let lastFix = null;
  for (let i = 0; i < data.hops.length; i++) {
    const h = data.hops[i];
    const here = (h.off_venue || h.floor == null) ? lastFix : h;
    if (here && here.x_pct != null) lastFix = here;
    if (i > 0 && here) {
      const prev = [...segments].reverse().find(s => s.type === 'sit' && s.at && s.at.floor != null);
      const moved = prev && (prev.at.floor !== here.floor || prev.at.x_pct !== here.x_pct || prev.at.y_pct !== here.y_pct);
      if (moved) {
        segments.push({ type: 'hop', from: prev.at, to: here, startT: cursor, endT: cursor + HOP_MS, toIdx: i });
        cursor += HOP_MS;
      }
    }
    segments.push({ type: 'sit', at: here || h, startT: cursor, endT: cursor + SIT_MS, idx: i, hop: h });
    cursor += SIT_MS;
  }
  const totalT = cursor || 1;

  /* SVG helpers */
  const SVG_NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  /* Per-floor render: labels + pins + trail. Called when the active floor
     changes. Pins use the hop index so we can color the "next" target white. */
  function renderFloor(floor) {
    clear(labelsGroup);
    clear(pinsGroup);
    // All rooms on this floor → faint labels
    const allRooms = data.rooms || {};
    for (const [name, r] of Object.entries(allRooms)) {
      if (r.floor !== floor) continue;
      // Slight downward offset so the label sits below the room centroid
      // and doesn't overlap the marker glow.
      const t = el('text', { x: r.x_pct, y: r.y_pct + 4.2, class: 'walk-label' });
      t.textContent = name;
      labelsGroup.appendChild(t);
    }
    // Stops on this floor → pins + trail
    const stopHops = segments.filter(s => s.type === 'sit' && s.at && s.at.floor === floor && s.at.x_pct != null);
    stopHops.forEach((s, i) => {
      const pin = el('circle', { cx: s.at.x_pct, cy: s.at.y_pct, r: 1.4, class: 'walk-pin' });
      pin.dataset.hopIdx = String(s.idx);
      pinsGroup.appendChild(pin);
    });
    const pts = stopHops.map(s => [s.at.x_pct, s.at.y_pct]);
    const d = pts.length >= 2
      ? pts.reduce((acc, [x, y], i) => acc + (i ? ' L ' : 'M ') + x.toFixed(2) + ' ' + y.toFixed(2), '')
      : '';
    trail.setAttribute('d', d);
    trail.classList.toggle('is-visible', !!d);
  }

  let currentFloor = null;
  function showFloor(floor) {
    if (floor == null || floor === currentFloor) return;
    currentFloor = floor;
    floorImgs.forEach(img => img.classList.toggle('is-current', String(img.dataset.floor) === String(floor)));
    if (floorLabel) {
      const meta = (data.floors && data.floors[String(floor)]) || {};
      floorLabel.textContent = meta.label || ('Level ' + floor);
    }
    renderFloor(floor);
  }

  function setMarkerXY(x, y) {
    marker.setAttribute('transform', `translate(${x.toFixed(2)} ${y.toFixed(2)})`);
  }
  function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }

  function setCard(seg) {
    if (!wcTitle) return;
    if (seg.type === 'sit') {
      const h = seg.hop;
      wcEyebrow.textContent = h.off_venue ? 'Off-venue stop' : (h.start_time ? `In session · ${h.start_time}` : 'In session');
      wcTitle.textContent = h.title || '';
      wcMeta.textContent = [h.room || (h.off_venue ? 'No mapped room' : ''), h.track || ''].filter(Boolean).join(' · ');
    } else {
      wcEyebrow.textContent = '🚶 Walking…';
      wcTitle.textContent = `${seg.from.room || '?'} → ${seg.to.room || '?'}`;
      wcMeta.textContent = seg.from.floor !== seg.to.floor
        ? `Level ${seg.from.floor} → Level ${seg.to.floor}`
        : `Same floor — Level ${seg.from.floor}`;
    }
  }

  function highlight(idx) {
    stops.forEach((li, i) => li.classList.toggle('is-current', i === idx));
    // Update pin colors: walked = orange, current = white, future = orange.
    Array.from(pinsGroup.children).forEach(p => {
      p.classList.toggle('is-next', parseInt(p.dataset.hopIdx, 10) === idx);
    });
  }

  function applyAt(t) {
    t = Math.max(0, Math.min(totalT, t));
    let seg = segments[0];
    for (const s of segments) { if (t >= s.startT && t <= s.endT) { seg = s; break; } }
    if (seg.type === 'sit') {
      const a = seg.at;
      showFloor(a && a.floor);
      if (a && a.x_pct != null) setMarkerXY(a.x_pct, a.y_pct);
      setCard(seg);
      highlight(seg.idx);
    } else {
      const tt = Math.max(0, Math.min(1, (t - seg.startT) / Math.max(1, seg.endT - seg.startT)));
      const e = ease(tt);
      if (seg.from.floor !== seg.to.floor) {
        showFloor(tt < 0.5 ? seg.from.floor : seg.to.floor);
      } else {
        showFloor(seg.from.floor);
      }
      const x = seg.from.x_pct + (seg.to.x_pct - seg.from.x_pct) * e;
      const y = seg.from.y_pct + (seg.to.y_pct - seg.from.y_pct) * e;
      setMarkerXY(x, y);
      setCard(seg);
      highlight(seg.toIdx);
    }
    const pct = (t / totalT) * 100;
    scrub.value = String(Math.round(pct * 10));
    scrub.style.setProperty('--progress', pct + '%');
  }

  let playing = false;
  let rafId = null;
  let lastFrame = null;
  let virtualT = 0;
  function tick(ts) {
    if (!lastFrame) lastFrame = ts;
    const dt = ts - lastFrame;
    lastFrame = ts;
    virtualT += dt;
    if (virtualT >= totalT) {
      virtualT = totalT;
      applyAt(virtualT);
      setPlaying(false);
      return;
    }
    applyAt(virtualT);
    rafId = requestAnimationFrame(tick);
  }
  function setPlaying(on) {
    playing = on;
    playBtn.setAttribute('aria-pressed', String(on));
    stage.classList.toggle('is-playing', on);
    if (on) {
      if (virtualT >= totalT) virtualT = 0;
      lastFrame = null;
      rafId = requestAnimationFrame(tick);
    } else if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }
  playBtn.addEventListener('click', () => setPlaying(!playing));
  rewind && rewind.addEventListener('click', () => { virtualT = 0; applyAt(0); if (playing) { lastFrame = null; rafId = requestAnimationFrame(tick); } });
  scrub.addEventListener('input', () => {
    setPlaying(false);
    virtualT = (parseInt(scrub.value, 10) / 1000) * totalT;
    applyAt(virtualT);
  });
  stops.forEach((li) => {
    li.addEventListener('click', () => {
      const idx = parseInt(li.dataset.idx || '0', 10);
      const target = segments.find(s => s.type === 'sit' && s.idx === idx);
      if (!target) return;
      setPlaying(false);
      virtualT = target.startT + 1;
      applyAt(virtualT);
    });
  });

  // Initial paint at t=0 — gets the marker to the first stop, picks the
  // right floor, and draws pins/labels/trail.
  applyAt(0);
})();
