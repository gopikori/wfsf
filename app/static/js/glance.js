/* glance.js — tap a glance block to reveal its details in a bottom sheet; tap
   anywhere outside the sheet (the scrim) to return to the calendar. Self-
   contained: does not depend on app.js, so the public shared page works alone. */
(function () {
  'use strict';

  var STATE = {
    primary:  { label: '✓ Attending' },
    conflict: { label: '⚠ Conflict — overbooked' },
    backup:   { label: '↻ Backup' },
    empty:    { label: 'Free' },
    past:     { label: 'Past' }
  };

  function $(id) { return document.getElementById(id); }

  function openSheet(block) {
    var sheet = $('glance-sheet');
    if (!sheet) return;
    var state = block.getAttribute('data-state') || 'empty';
    var start = block.getAttribute('data-start') || '';
    var end = block.getAttribute('data-end') || '';
    var info = STATE[state] || STATE.empty;

    $('gs-time').textContent = end ? (start + ' – ' + end) : start;
    var st = $('gs-state');
    st.textContent = info.label;
    st.className = 'gs-state state-' + state;

    var body = $('gs-body');
    body.innerHTML = '';
    var detailId = block.getAttribute('data-detail');
    var src = detailId ? $(detailId) : null;
    if (src) {
      body.innerHTML = src.innerHTML;
    } else {
      var avail = block.getAttribute('data-available') || '0';
      var d = document.createElement('div');
      d.className = 'gs-free';
      d.innerHTML = '<strong>Nothing booked</strong>' +
        '<span>' + avail + ' session' + (avail === '1' ? '' : 's') + ' available in this slot</span>';
      body.appendChild(d);
    }

    document.querySelectorAll('.glance-block.is-open').forEach(function (b) { b.classList.remove('is-open'); });
    block.classList.add('is-open');
    sheet.hidden = false;
    sheet.setAttribute('aria-hidden', 'false');
    if (window.navigator && navigator.vibrate) { try { navigator.vibrate(8); } catch (e) {} }
  }

  function closeSheet() {
    var sheet = $('glance-sheet');
    if (!sheet || sheet.hidden) return;
    sheet.hidden = true;
    sheet.setAttribute('aria-hidden', 'true');
    document.querySelectorAll('.glance-block.is-open').forEach(function (b) { b.classList.remove('is-open'); });
  }

  function bindCopy(e) {
    var btn = e.target.closest('[data-copy]');
    if (!btn) return;
    var box = btn.closest('.share-box') || document;
    var input = box.querySelector('[data-copy-src]');
    if (!input) return;
    var done = function () { btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = 'Copy'; }, 1600); };
    input.select();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(input.value).then(done, function () { document.execCommand('copy'); done(); });
    } else { try { document.execCommand('copy'); } catch (err) {} done(); }
  }

  function closeShare() {
    var pop = document.querySelector('.share-pop[open]');
    if (pop) pop.open = false;
  }

  function init() {
    document.querySelectorAll('.glance-block').forEach(function (block) {
      block.addEventListener('click', function () { openSheet(block); });
    });
    document.addEventListener('click', function (e) {
      if (e.target.closest('[data-close-glance]')) { closeSheet(); return; }
      // share popover: ✕ button or any click outside it closes (the opening
      // summary-click runs before <details> flips to [open], so it won't self-close)
      if (e.target.closest('[data-close-share]') ||
          (document.querySelector('.share-pop[open]') && !e.target.closest('.share-pop'))) {
        closeShare();
      }
      bindCopy(e);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { closeSheet(); closeShare(); }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
