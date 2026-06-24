/* Immersive walk preview.
 *
 * The server still emits simple stops and floor centroids. This script turns
 * that data into a 2.5D venue scene: all floors stay visible, the active floor
 * brightens, floor changes get a transfer column, and playback can switch
 * between stacked and focused camera modes.
 */
(function () {
  const data = (() => {
    const tag = document.getElementById('walk-data');
    if (!tag) return null;
    try { return JSON.parse(tag.textContent || '{}'); } catch (_) { return null; }
  })();
  if (!data || !Array.isArray(data.hops) || !data.hops.length) return;

  const stage = document.getElementById('walk-stage');
  const playBtn = document.getElementById('walk-play');
  const scrub = document.getElementById('walk-scrub');
  const rewind = document.getElementById('walk-rewind');
  const floorLabel = document.getElementById('walk-floor-label');
  const legLabel = document.getElementById('walk-leg-label');
  const wcEyebrow = document.getElementById('wc-eyebrow');
  const wcTitle = document.getElementById('wc-title');
  const wcMeta = document.getElementById('wc-meta');
  const stackMode = document.getElementById('walk-mode-stack');
  const focusMode = document.getElementById('walk-mode-focus');
  const screenTip = document.getElementById('walk-screen-tip');
  const tipTitle = document.getElementById('walk-tip-title');
  const tipMeta = document.getElementById('walk-tip-meta');
  const stops = Array.from(document.querySelectorAll('.walk-stop'));
  const floorNodes = new Map();
  if (!stage || !playBtn || !scrub) return;

  const SIT_MS = 1500;
  const HOP_MS = 1200;
  const SVG_NS = 'http://www.w3.org/2000/svg';

  document.querySelectorAll('.walk-floor-layer').forEach((layer) => {
    const floor = Number(layer.dataset.floor);
    const svg = layer.querySelector('.walk-floor-svg');
    floorNodes.set(floor, {
      svg,
      layer,
      base: svg.querySelector('[data-role="route-base"]'),
      active: svg.querySelector('[data-role="route-active"]'),
      pins: svg.querySelector('[data-role="pins"]'),
      labels: svg.querySelector('[data-role="labels"]'),
      marker: svg.querySelector('[data-role="marker"]'),
    });
  });

  function hasFix(h) {
    return h && !h.off_venue && h.floor != null && h.x_pct != null && h.y_pct != null;
  }

  const segments = [];
  let cursor = 0;
  let lastFix = null;
  for (let i = 0; i < data.hops.length; i++) {
    const raw = data.hops[i];
    const here = hasFix(raw) ? raw : lastFix;
    if (hasFix(raw)) lastFix = raw;
    if (i > 0 && here) {
      const prev = [...segments].reverse().find(s => s.type === 'sit' && hasFix(s.at));
      const moved = prev && (
        prev.at.floor !== here.floor ||
        prev.at.x_pct !== here.x_pct ||
        prev.at.y_pct !== here.y_pct
      );
      if (moved) {
        segments.push({ type: 'hop', from: prev.at, to: here, startT: cursor, endT: cursor + HOP_MS, toIdx: i });
        cursor += HOP_MS;
      }
    }
    segments.push({ type: 'sit', at: here || raw, startT: cursor, endT: cursor + SIT_MS, idx: i, hop: raw });
    cursor += SIT_MS;
  }
  const totalT = cursor || 1;

  function el(tag, attrs) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  function floorMeta(floor) {
    return (data.floors && data.floors[String(floor)]) || {};
  }

  function pathFrom(points) {
    if (points.length < 2) return '';
    return points.reduce((acc, p, i) => (
      acc + (i ? ' L ' : 'M ') + Number(p.x_pct).toFixed(2) + ' ' + Number(p.y_pct).toFixed(2)
    ), '');
  }

  function renderFloorRoutes() {
    floorNodes.forEach((node, floor) => {
      clear(node.labels);
      clear(node.pins);
      node.active.setAttribute('d', '');

      Object.entries(data.rooms || {}).forEach(([name, room]) => {
        if (Number(room.floor) !== floor) return;
        const label = el('text', { x: room.x_pct, y: room.y_pct + 4.1, class: 'walk-label' });
        label.textContent = name;
        node.labels.appendChild(label);
      });

      const stopsOnFloor = segments.filter(s => s.type === 'sit' && hasFix(s.at) && Number(s.at.floor) === floor);
      node.base.setAttribute('d', pathFrom(stopsOnFloor.map(s => s.at)));
      stopsOnFloor.forEach((s) => {
        const pin = el('circle', { cx: s.at.x_pct, cy: s.at.y_pct, r: 1.45, class: 'walk-pin' });
        pin.dataset.idx = String(s.idx);
        node.pins.appendChild(pin);
      });
    });
  }

  let currentFloor = null;
  function showFloor(floor, transfer) {
    if (floor == null) return;
    currentFloor = Number(floor);
    floorNodes.forEach((node, f) => {
      node.layer.classList.toggle('is-active', f === currentFloor);
      node.layer.classList.toggle('is-above', f > currentFloor);
      node.layer.classList.toggle('is-below', f < currentFloor);
      node.layer.classList.toggle('is-transfer', !!transfer && (f === transfer.from.floor || f === transfer.to.floor));
      node.marker.classList.toggle('is-visible', f === currentFloor);
      node.active.setAttribute('d', '');
    });
    if (floorLabel) floorLabel.textContent = floorMeta(currentFloor).label || ('Level ' + currentFloor);
  }

  function setMarker(floor, x, y) {
    const node = floorNodes.get(Number(floor));
    if (!node) return;
    node.marker.setAttribute('transform', `translate(${Number(x).toFixed(2)} ${Number(y).toFixed(2)})`);
  }

  function truncate(value, max) {
    const text = String(value || '').trim();
    return text.length > max ? text.slice(0, max - 1) + '...' : text;
  }

  function setTooltip(floor, hop, x, y) {
    hideTooltips();
    const node = floorNodes.get(Number(floor));
    if (!node || !screenTip || !tipTitle || !tipMeta || !hop || hop.off_venue) return;
    const point = node.svg.createSVGPoint();
    point.x = Number(x);
    point.y = Number(y);
    const screenPoint = point.matrixTransform(node.svg.getScreenCTM());
    const stageRect = stage.getBoundingClientRect();
    screenTip.style.left = `${screenPoint.x - stageRect.left}px`;
    screenTip.style.top = `${screenPoint.y - stageRect.top}px`;
    tipTitle.textContent = truncate(hop.title, 34);
    tipMeta.textContent = truncate([hop.start_time, hop.room].filter(Boolean).join(' | '), 34);
    screenTip.classList.add('is-visible');
  }

  function hideTooltips() {
    screenTip && screenTip.classList.remove('is-visible');
  }

  function setActiveLeg(floor, from, to) {
    const node = floorNodes.get(Number(floor));
    if (!node || !from || !to) return;
    node.active.setAttribute('d', pathFrom([from, to]));
  }

  function setTransferColumn(seg, t) {
    floorNodes.forEach(node => node.layer.classList.remove('is-transfer-from', 'is-transfer-to'));
    if (!seg || seg.from.floor === seg.to.floor) return;
    const fromNode = floorNodes.get(Number(seg.from.floor));
    const toNode = floorNodes.get(Number(seg.to.floor));
    if (!fromNode || !toNode) return;
    fromNode.layer.style.setProperty('--lift-x', seg.from.x_pct + '%');
    fromNode.layer.style.setProperty('--lift-y', seg.from.y_pct + '%');
    toNode.layer.style.setProperty('--lift-x', seg.to.x_pct + '%');
    toNode.layer.style.setProperty('--lift-y', seg.to.y_pct + '%');
    fromNode.layer.classList.add('is-transfer-from');
    toNode.layer.classList.add('is-transfer-to');
    if (legLabel) legLabel.textContent = `Change levels: L${seg.from.floor} to L${seg.to.floor}`;
    if (t > 0.48 && t < 0.52) stage.classList.add('is-level-hop');
    else stage.classList.remove('is-level-hop');
  }

  function clearTransferColumn() {
    stage.classList.remove('is-level-hop');
    floorNodes.forEach(node => {
      node.layer.classList.remove('is-transfer-from', 'is-transfer-to');
    });
  }

  function ease(t) {
    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
  }

  function transferEstimate(from, to) {
    if (!from || !to) return '';
    const dx = Number(to.x_pct) - Number(from.x_pct);
    const dy = Number(to.y_pct) - Number(from.y_pct);
    const mapSteps = Math.sqrt(dx * dx + dy * dy);
    const floorPenalty = Math.abs(Number(to.floor) - Number(from.floor)) * 3;
    const mins = Math.max(1, Math.round(mapSteps / 18 + floorPenalty + 1));
    return `${mins} min estimated transfer`;
  }

  function setCard(seg) {
    if (!wcTitle) return;
    if (seg.type === 'sit') {
      const h = seg.hop;
      wcEyebrow.textContent = h.off_venue ? 'Off-venue stop' : (h.start_time ? `In session · ${h.start_time}` : 'In session');
      wcTitle.textContent = h.title || '';
      wcMeta.textContent = [h.room || (h.off_venue ? 'No mapped room' : ''), h.track || ''].filter(Boolean).join(' · ');
      if (legLabel) legLabel.textContent = h.room ? `Stop: ${h.room}` : 'Stop outside mapped venue';
      return;
    }
    wcEyebrow.textContent = 'Walking';
    wcTitle.textContent = `${seg.from.room || 'Previous room'} -> ${seg.to.room || 'Next room'}`;
    wcMeta.textContent = [
      seg.from.floor === seg.to.floor ? `Same floor: L${seg.from.floor}` : `Level ${seg.from.floor} to level ${seg.to.floor}`,
      transferEstimate(seg.from, seg.to),
    ].filter(Boolean).join(' · ');
  }

  function highlight(idx) {
    stops.forEach((li, i) => li.classList.toggle('is-current', i === idx));
    floorNodes.forEach((node) => {
      Array.from(node.pins.children).forEach((pin) => {
        const pinIdx = Number(pin.dataset.idx);
        pin.classList.toggle('is-current', pinIdx === idx);
        pin.classList.toggle('is-done', pinIdx < idx);
      });
    });
  }

  function applyAt(t) {
    t = Math.max(0, Math.min(totalT, t));
    let seg = segments[0];
    for (const s of segments) {
      if (t >= s.startT && t <= s.endT) { seg = s; break; }
    }

    if (seg.type === 'sit') {
      const a = seg.at;
      clearTransferColumn();
      if (hasFix(a)) {
        showFloor(a.floor);
        setMarker(a.floor, a.x_pct, a.y_pct);
        setTooltip(a.floor, seg.hop, a.x_pct, a.y_pct);
      }
      setCard(seg);
      highlight(seg.idx);
    } else {
      const tt = Math.max(0, Math.min(1, (t - seg.startT) / Math.max(1, seg.endT - seg.startT)));
      const e = ease(tt);
      const changingFloors = seg.from.floor !== seg.to.floor;
      const activeFloor = changingFloors && tt >= 0.5 ? seg.to.floor : seg.from.floor;
      showFloor(activeFloor, changingFloors ? seg : null);
      hideTooltips();
      setTransferColumn(changingFloors ? seg : null, tt);
      if (changingFloors) {
        const point = tt < 0.5 ? seg.from : seg.to;
        setMarker(activeFloor, point.x_pct, point.y_pct);
      } else {
        const x = seg.from.x_pct + (seg.to.x_pct - seg.from.x_pct) * e;
        const y = seg.from.y_pct + (seg.to.y_pct - seg.from.y_pct) * e;
        setMarker(activeFloor, x, y);
        setActiveLeg(activeFloor, seg.from, { x_pct: x, y_pct: y });
        if (legLabel) legLabel.textContent = `${seg.from.room || 'Room'} to ${seg.to.room || 'Room'}`;
      }
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
    virtualT += ts - lastFrame;
    lastFrame = ts;
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

  function setViewMode(mode) {
    const focus = mode === 'focus';
    stage.classList.toggle('is-focus-mode', focus);
    stage.classList.toggle('is-stack-mode', !focus);
    stackMode && stackMode.classList.toggle('is-active', !focus);
    focusMode && focusMode.classList.toggle('is-active', focus);
  }

  playBtn.addEventListener('click', () => setPlaying(!playing));
  rewind && rewind.addEventListener('click', () => {
    virtualT = 0;
    applyAt(0);
    if (playing) {
      lastFrame = null;
      rafId = requestAnimationFrame(tick);
    }
  });
  scrub.addEventListener('input', () => {
    setPlaying(false);
    virtualT = (Number(scrub.value) / 1000) * totalT;
    applyAt(virtualT);
  });
  stackMode && stackMode.addEventListener('click', () => setViewMode('stack'));
  focusMode && focusMode.addEventListener('click', () => setViewMode('focus'));
  stops.forEach((li) => {
    li.addEventListener('click', () => {
      const idx = Number(li.dataset.idx || '0');
      const target = segments.find(s => s.type === 'sit' && s.idx === idx);
      if (!target) return;
      setPlaying(false);
      virtualT = target.startT + 1;
      applyAt(virtualT);
    });
  });

  renderFloorRoutes();
  applyAt(0);
})();
