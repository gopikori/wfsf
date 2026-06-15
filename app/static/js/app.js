(function () {
  function bindClock() {
    const el = document.getElementById('liveclock');
    if (!el) return;
    if (el.dataset.frozen === '1') return;
    const fmt = () => {
      const d = new Date();
      const date = d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
      const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
      el.textContent = `${date} · ${time}`;
    };
    fmt();
    setInterval(fmt, 30000);
  }

  function bindCountdowns() {
    const tick = () => {
      document.querySelectorAll('.countdown[data-start]').forEach(el => {
        if (el.dataset.frozen === '1') return;
        const start = new Date(el.dataset.start);
        if (Number.isNaN(start.getTime())) return;
        const diff = start - new Date();
        if (diff <= 0) { el.textContent = 'Starting now'; return; }
        const min = Math.floor(diff / 60000);
        const hr = Math.floor(min / 60);
        el.textContent = hr > 0 ? `Starts in ${hr}h ${min % 60}m` : `Starts in ${min}m`;
      });
    };
    tick();
    setInterval(tick, 30000);
  }

  function flash(text, kind) {
    const container = document.getElementById('toasts');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${kind || ''}`.trim();
    el.textContent = text;
    container.appendChild(el);
    setTimeout(() => el.remove(), 2400);
  }

  function syncResultCount() {
    const list = document.getElementById('session-list');
    const count = document.getElementById('result-count');
    if (list && count && list.dataset.total != null) {
      count.textContent = list.dataset.total;
    }
  }

  function bindToasts() {
    // syncResultCount runs per swap so the OOB chrome refresh keeps the count
    // chip honest. Toast logic is on afterRequest (fires once per HTTP request)
    // — otherwise the OOB day-chrome swap would double-fire the message.
    document.body.addEventListener('htmx:afterSwap', () => {
      syncResultCount();
    });
    // Derive intent from the request path. The htmx:afterSwap `target` for
    // hx-swap="outerHTML" references the now-detached old form, so its DOM
    // reflects the PRE-swap state — querying it for `.btn.attending` would
    // invert the toast (worked once, broken forever after).
    document.body.addEventListener('htmx:afterRequest', (e) => {
      const xhr = e.detail && e.detail.xhr;
      if (!xhr || xhr.status < 200 || xhr.status >= 300) return;
      const req = e.detail && e.detail.requestConfig;
      const path = (req && req.path) || (e.detail && e.detail.pathInfo && e.detail.pathInfo.requestPath) || '';
      if (/\/session\/\d+\/save$/.test(path)) {
        flash('Attending — added to your plan', 'ok');
      } else if (/\/session\/\d+\/unsave$/.test(path)) {
        flash('Removed from your plan', '');
      }
    });
    document.body.addEventListener('htmx:responseError', () => {
      flash('Something went wrong. Please try again.', 'err');
    });
  }

  function openSheet(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.setAttribute('aria-hidden', 'false');
    document.body.classList.add('sheet-open');
    document.body.dispatchEvent(new CustomEvent('open-sheet'));
    const firstFocus = el.querySelector('.sheet-close, input, button');
    if (firstFocus) setTimeout(() => firstFocus.focus(), 60);
  }
  function closeSheet(el) {
    if (!el) return;
    el.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('sheet-open');
  }
  function bindSheet() {
    document.addEventListener('click', (e) => {
      const trigger = e.target.closest('[data-open-sheet]');
      if (trigger) {
        e.preventDefault();
        openSheet(trigger.dataset.openSheet);
        return;
      }
      const closer = e.target.closest('[data-close-sheet]');
      if (closer) {
        e.preventDefault();
        const sheet = closer.closest('.sheet');
        closeSheet(sheet);
        return;
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.sheet[aria-hidden="false"]').forEach(closeSheet);
      }
    });
  }

  function bindTypeahead() {
    document.addEventListener('input', (e) => {
      const input = e.target.closest('input[data-typeahead]');
      if (!input) return;
      const list = document.getElementById(input.dataset.typeahead);
      if (!list) return;
      const q = (input.value || '').trim().toLowerCase();
      list.querySelectorAll('.opt-row').forEach(row => {
        const label = row.dataset.label || '';
        row.classList.toggle('is-hidden', q && !label.includes(q));
      });
    });
  }

  function bindActiveChipRemove() {
    document.addEventListener('click', (e) => {
      const chip = e.target.closest('.active-chip[data-remove-filter]');
      if (!chip) return;
      e.preventDefault();
      const dim = chip.dataset.removeFilter;
      const val = chip.dataset.removeValue;
      const inputs = document.querySelectorAll(
        `input[name="${dim}"][value="${CSS.escape(val)}"]`
      );
      inputs.forEach(i => { if (i.checked) i.checked = false; });
      const form = document.getElementById('filters');
      if (form) form.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  let observerSuppressedUntil = 0;
  function suppressObserverFor(ms) {
    observerSuppressedUntil = Date.now() + ms;
  }
  function isObserverSuppressed() {
    return Date.now() < observerSuppressedUntil;
  }

  function scrollToSlot(anchorId, smooth) {
    const el = document.getElementById(anchorId);
    if (!el) return;
    // If this slot is the LAST one inside its day-block (next sibling is the
    // fixed .day-chrome), aligning its top to viewport-top leaves a huge dead
    // area between its cards and the chrome. Align its bottom instead so it
    // lands just above the chrome with prior slots' cards above for context.
    const next = el.nextElementSibling;
    const isLastInBlock = next && next.classList && next.classList.contains('day-chrome');
    el.scrollIntoView({
      behavior: smooth ? 'smooth' : 'auto',
      block: isLastInBlock ? 'end' : 'start',
    });
  }
  function markCurrentPill(anchorId) {
    document.querySelectorAll('.time-pill.is-current').forEach(p => p.classList.remove('is-current'));
    if (!anchorId) return;
    const pill = document.querySelector(`.time-pill[data-slot-anchor="${anchorId}"]`);
    if (pill) {
      pill.classList.add('is-current');
      pill.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
  }
  function bindTimeStrip() {
    document.addEventListener('click', (e) => {
      const link = e.target.closest('.time-pill[data-slot-anchor]');
      if (!link) return;
      e.preventDefault();
      const id = link.dataset.slotAnchor;
      suppressObserverFor(1400);
      scrollToSlot(id, true);
      markCurrentPill(id);
      if (history.replaceState) history.replaceState(null, '', '#' + id);
    });
  }
  function autoAnchorNow() {
    const today = new Date();
    const iso = today.toISOString().slice(0, 10);
    const block = document.querySelector(`.day-block[data-day-iso="${iso}"]`);
    if (!block) return;
    const nowHM = today.toTimeString().slice(0, 5);
    const pills = Array.from(block.querySelectorAll('.time-pill[data-time]'));
    if (!pills.length) return;
    let target = pills.find(p => (p.dataset.time || '') >= nowHM);
    if (!target) target = pills[pills.length - 1];
    const id = target.dataset.slotAnchor;
    if (!window.location.hash) scrollToSlot(id, false);
    markCurrentPill(id);
  }
  const SHAPE_STATE_GLYPH = { primary: '✓', backup: '↻', conflict: '⚠', past: '·', empty: '' };
  const SHAPE_STATE_LABEL = { primary: 'Attending', backup: 'Backup', conflict: 'Conflict', past: 'Past', empty: 'Free' };

  function ensureShapeLens() {
    let el = document.getElementById('shape-lens');
    if (!el) {
      el = document.createElement('div');
      el.id = 'shape-lens';
      el.className = 'shape-lens';
      el.setAttribute('aria-hidden', 'true');
      el.innerHTML =
        '<span class="ls-time"></span>' +
        '<span class="ls-state"></span>' +
        '<span class="ls-detail"></span>' +
        '<span class="ls-arrow"></span>';
      document.body.appendChild(el);
    }
    return el;
  }

  function updateShapeLens(seg, bar) {
    const lens = ensureShapeLens();
    const state = seg.dataset.state || 'empty';
    const time = seg.dataset.displayTime || 'TBA';
    const count = parseInt(seg.dataset.count || '0', 10) || 0;
    const picked = parseInt(seg.dataset.picked || '0', 10) || 0;
    const glyph = SHAPE_STATE_GLYPH[state] || '';
    const label = SHAPE_STATE_LABEL[state] || 'Free';
    lens.className = `shape-lens is-visible state-${state}`;
    lens.querySelector('.ls-time').textContent = time;
    lens.querySelector('.ls-state').textContent = glyph ? `${glyph} ${label}` : label;
    let detail;
    if (state === 'primary' || state === 'backup' || state === 'conflict') {
      detail = `${picked} of ${count} picked`;
    } else {
      detail = `${count} session${count === 1 ? '' : 's'}`;
    }
    lens.querySelector('.ls-detail').textContent = detail;
    const segRect = seg.getBoundingClientRect();
    const barRect = bar.getBoundingClientRect();
    const lensW = lens.offsetWidth || 130;
    const half = lensW / 2;
    const cx = segRect.left + segRect.width / 2;
    const minX = 8 + half;
    const maxX = window.innerWidth - 8 - half;
    const finalX = Math.max(minX, Math.min(maxX, cx));
    lens.style.left = `${finalX}px`;
    lens.style.top = `${barRect.top}px`;
    const arrow = lens.querySelector('.ls-arrow');
    if (arrow) arrow.style.left = `calc(50% + ${(cx - finalX).toFixed(1)}px)`;
  }

  function hideShapeLens() {
    const el = document.getElementById('shape-lens');
    if (el) el.classList.remove('is-visible');
  }

  function markActiveSeg(seg, bar) {
    bar.querySelectorAll('.shape-seg.is-active').forEach(s => s.classList.remove('is-active'));
    if (seg) seg.classList.add('is-active');
  }

  function bindShapeBarScrub() {
    document.querySelectorAll('.shape-bar').forEach(bar => {
      if (bar.dataset.bound === '1') return;
      bar.dataset.bound = '1';
      let scrubbing = false;
      let lastAnchor = null;
      let pendingScroll = null;

      function segAt(x, y) {
        const el = document.elementFromPoint(x, y);
        if (el) {
          const seg = el.closest('.shape-seg');
          if (seg && bar.contains(seg)) return seg;
        }
        const r = bar.getBoundingClientRect();
        const cx = Math.max(r.left + 1, Math.min(r.right - 1, x));
        const segs = Array.from(bar.querySelectorAll('.shape-seg'));
        if (!segs.length) return null;
        for (const s of segs) {
          const sr = s.getBoundingClientRect();
          if (cx >= sr.left && cx <= sr.right) return s;
        }
        let best = segs[0], bestD = Infinity;
        segs.forEach(s => {
          const sr = s.getBoundingClientRect();
          const c = (sr.left + sr.right) / 2;
          const d = Math.abs(c - cx);
          if (d < bestD) { bestD = d; best = s; }
        });
        return best;
      }

      function preview(seg) {
        if (!seg) return;
        const anchor = seg.dataset.slotAnchor;
        if (!anchor) return;
        markActiveSeg(seg, bar);
        updateShapeLens(seg, bar);
        if (anchor === lastAnchor) return;
        lastAnchor = anchor;
        markCurrentPill(anchor);
        if (pendingScroll) cancelAnimationFrame(pendingScroll);
        pendingScroll = requestAnimationFrame(() => scrollToSlot(anchor, false));
      }

      bar.addEventListener('pointerdown', (e) => {
        scrubbing = true;
        suppressObserverFor(60000);
        try { bar.setPointerCapture(e.pointerId); } catch (_) {}
        bar.classList.add('is-scrubbing');
        preview(segAt(e.clientX, e.clientY));
        e.preventDefault();
      });
      bar.addEventListener('pointermove', (e) => {
        if (!scrubbing) return;
        suppressObserverFor(2000);
        preview(segAt(e.clientX, e.clientY));
      });
      function end(e) {
        if (!scrubbing) return;
        scrubbing = false;
        bar.classList.remove('is-scrubbing');
        try { if (e && e.pointerId != null) bar.releasePointerCapture(e.pointerId); } catch (_) {}
        hideShapeLens();
        bar.querySelectorAll('.shape-seg.is-active').forEach(s => s.classList.remove('is-active'));
        if (lastAnchor) {
          suppressObserverFor(1500);
          scrollToSlot(lastAnchor, true);
        }
      }
      bar.addEventListener('pointerup', end);
      bar.addEventListener('pointercancel', end);
    });
  }

  function bindSlotObserver() {
    const slots = Array.from(document.querySelectorAll('.slot-block[id]'));
    if (!slots.length || !('IntersectionObserver' in window)) return;
    const obs = new IntersectionObserver((entries) => {
      if (isObserverSuppressed()) return;
      const visible = entries.filter(e => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible.length) markCurrentPill(visible[0].target.id);
    }, { rootMargin: '-70px 0px -60% 0px', threshold: 0 });
    slots.forEach(s => obs.observe(s));
  }

  function bindDayChromeSwitch() {
    const blocks = Array.from(document.querySelectorAll('.day-block'));
    if (!blocks.length) return;
    const activate = (block) => {
      document.querySelectorAll('.day-chrome.is-active').forEach(c => c.classList.remove('is-active'));
      const chrome = block.querySelector('.day-chrome');
      if (chrome) chrome.classList.add('is-active');
    };
    activate(blocks[0]);
    if (!('IntersectionObserver' in window)) return;
    const obs = new IntersectionObserver((entries) => {
      const visible = entries
        .filter(e => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible.length) activate(visible[0].target);
    }, { rootMargin: '-25% 0px -55% 0px', threshold: 0 });
    blocks.forEach(b => obs.observe(b));
  }

  function bindReminders() {
    const els = document.querySelectorAll('.next-link, .now-link');
    if (!els.length) return;
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'default') return;
    document.body.addEventListener('click', () => {
      if (Notification.permission === 'default') {
        Notification.requestPermission().catch(() => {});
      }
    }, { once: true });
  }

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(() => {
    bindClock();
    bindCountdowns();
    bindToasts();
    bindReminders();
    bindSheet();
    bindTypeahead();
    bindActiveChipRemove();
    bindTimeStrip();
    autoAnchorNow();
    bindSlotObserver();
    bindShapeBarScrub();
    bindDayChromeSwitch();
    document.body.addEventListener('htmx:afterSwap', (e) => {
      if (!e.detail || !e.detail.target) return;
      if (e.detail.target.id === 'results-region') {
        autoAnchorNow();
        bindSlotObserver();
        bindShapeBarScrub();
        bindDayChromeSwitch();
      }
    });
    // After save/unsave the OOB chrome swap replaces the day-chrome and the
    // server response markup omits .is-active. .day-chrome defaults to
    // display:none, so without re-adding the class the whole bottom bar
    // vanishes.
    //
    // We MUST run after htmx:afterSettle, not afterRequest. htmx's class
    // settle phase runs AFTER afterRequest and authoritatively overwrites
    // the node's className with the response markup's value — any is-active
    // we add at afterRequest gets immediately wiped. afterSettle fires last
    // and leaves the className finalized; reassertions stick.
    //
    // Look up the affected day deterministically: session_id (from request
    // path) → new save-form button → enclosing .day-block[data-day-index].
    // Skip non-save/unsave requests up front.
    document.body.addEventListener('htmx:afterSettle', (e) => {
      const xhr = e.detail && e.detail.xhr;
      if (!xhr || xhr.status < 200 || xhr.status >= 300) return;
      const req = e.detail && e.detail.requestConfig;
      const path = (req && req.path) || '';
      const m = path.match(/\/session\/(\d+)\/(save|unsave)$/);
      if (!m) return;
      const sid = m[1];
      const btn = document.querySelector(
        `form.save-form button[hx-post="/session/${sid}/save"], form.save-form button[hx-post="/session/${sid}/unsave"]`
      );
      const block = btn && btn.closest('.day-block');
      const di = block && block.dataset.dayIndex;
      if (di != null) {
        document.querySelectorAll('.day-chrome.is-active').forEach(c => c.classList.remove('is-active'));
        const chrome = document.getElementById(`chrome-day-${di}`);
        if (chrome) chrome.classList.add('is-active');
      }
      // The freshly-swapped chrome's .shape-bar is a brand-new node — its
      // dataset.bound guard never ran, so pointer events would no-op.
      bindShapeBarScrub();
    });
  });
})();
