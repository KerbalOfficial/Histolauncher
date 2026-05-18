// ui/modules/playtime-detail-modal.js

import { api } from './api.js';
import { showMessageBox } from './modal.js';
import { escapeInfoHtml } from './string-utils.js';
import { t } from './i18n.js';
import { unicodeList } from './config.js';
import { renderCommonPagination } from './pagination.js';

const PAGE_SIZE = 20;

let _ms = null;

const _fmt = (s) => {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  return `${m}m`;
};

const fmtDateTime = (ts) => {
  if (!ts) return unicodeList.empty;
  try {
    const d = new Date(Number(ts) * 1000);
    const fmt = t('dateTimeFormat') || 'MM/DD/YYYY HH:mm';
    const h24 = d.getHours();
    const h12 = h24 % 12 || 12;
    const tokens = {
      'YYYY': String(d.getFullYear()),
      'MM':   String(d.getMonth() + 1).padStart(2, '0'),
      'DD':   String(d.getDate()).padStart(2, '0'),
      'HH':   String(h24).padStart(2, '0'),
      'hh':   String(h12).padStart(2, '0'),
      'mm':   String(d.getMinutes()).padStart(2, '0'),
      'A':    h24 < 12 ? t('am') || 'AM' : t('pm') || 'PM',
      'a':    h24 < 12 ? (t('am') || 'AM').toLowerCase() : (t('pm') || 'PM').toLowerCase(),
    };
    return fmt.replace(/YYYY|MM|DD|HH|hh|mm|A(?!M)|a(?!m)/g, (match) => tokens[match] ?? match);
  } catch (_) {
    return unicodeList.empty;
  }
};

const _getSortValue = (s, key) => {
  if (key === 'date')     return s.started_at || 0;
  if (key === 'version')  return (s.version || '').toLowerCase();
  if (key === 'duration') return s.duration_s || 0;
  if (key === 'loader')   return (s.loader || '').toLowerCase();
  return 0;
};

const _sorted = (sessions, key, dir) =>
  [...sessions].sort((a, b) => {
    const av = _getSortValue(a, key);
    const bv = _getSortValue(b, key);
    if (av < bv) return dir === 'asc' ? -1 : 1;
    if (av > bv) return dir === 'asc' ? 1 : -1;
    return 0;
  });

const _applyFilters = (sessions) => {
  if (!_ms) return sessions;
  let out = sessions;
  if (_ms.versionFilter !== '__all__') out = out.filter((s) => s.version === _ms.versionFilter);
  if (_ms.loaderFilter !== '__all__') {
    if (_ms.loaderFilter === '__none__') {
      out = out.filter((s) => !s.loader);
    } else {
      out = out.filter((s) => s.loader === _ms.loaderFilter);
    }
  }
  return out;
};

const _rerender = () => {
  if (!_ms) return;
  const { sortKey, sortDir } = _ms;

  const sourceSessions = _ms.liveSession
    ? [_ms.liveSession, ..._ms.sessions]
    : _ms.sessions;
  const filtered = _applyFilters(sourceSessions);
  const ordered = _sorted(filtered, sortKey, sortDir);
  const totalPages = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE));
  if (_ms.currentPage > totalPages) _ms.currentPage = totalPages;

  const pageStart = (_ms.currentPage - 1) * PAGE_SIZE;
  const pageItems = ordered.slice(pageStart, pageStart + PAGE_SIZE);

  // ---- update Total ----
  const totalEl = document.getElementById('playtime-detail-total-val');
  if (totalEl) {
    const totalS = filtered.reduce((acc, s) => acc + (s.duration_s || 0), 0);
    totalEl.textContent = _fmt(totalS);
  }

  // ---- truncation notice ----
  const truncEl = document.getElementById('playtime-detail-trunc');
  if (truncEl && _ms.total > _ms.sessions.length) {
    truncEl.textContent = t('settings.playtime.detail.truncatedNote')
      .replace('{shown}', String(_ms.sessions.length))
      .replace('{total}', String(_ms.total));
    truncEl.classList.remove('hidden');
  } else if (truncEl) {
    truncEl.classList.add('hidden');
  }

  // ---- rebuild table ----
  const listEl = document.getElementById('playtime-detail-list');
  if (listEl) {
    const focusedTh = document.activeElement?.closest?.('.playtime-sort-th');
    const focusedColKey = focusedTh?.dataset?.colKey ?? null;
    const focusedIsRow = !focusedTh && document.activeElement?.closest?.('thead tr') !== null
      && document.activeElement?.closest?.('.playtime-detail-list') !== null;

    listEl.innerHTML = '';
    if (pageItems.length === 0 && !_ms.liveSession) {
      const p = document.createElement('p');
      p.className = 'playtime-detail-empty';
      p.textContent = t('settings.playtime.detail.noSessions');
      listEl.appendChild(p);
    } else {
      const cols = [
        { key: 'date',     label: t('settings.playtime.detail.date') },
        { key: 'version',  label: t('settings.playtime.detail.version') },
        { key: 'duration', label: t('settings.playtime.detail.duration') },
        { key: 'loader',   label: t('settings.playtime.detail.modloader') },
      ];

      const table = document.createElement('table');
      table.className = 'playtime-detail-table';

      const thead = document.createElement('thead');
      const headerRow = document.createElement('tr');
      headerRow.setAttribute('tabindex', '0');
      headerRow.setAttribute('role', 'row');
      headerRow.setAttribute('aria-label', t('settings.playtime.detail.sortBy'));

      for (const col of cols) {
        const th = document.createElement('th');
        th.className = 'playtime-sort-th' + (sortKey === col.key ? ' active' : '');
        th.title = t('settings.playtime.detail.sortBy');
        th.style.cursor = 'pointer';
        th.setAttribute('tabindex', '-1'); 
        th.setAttribute('role', 'columnheader');
        th.setAttribute('aria-sort', sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none');
        th.dataset.colKey = col.key;

        const labelSpan = document.createElement('span');
        labelSpan.textContent = col.label;
        th.appendChild(labelSpan);

        const arrow = document.createElement('span');
        arrow.className = 'sort-arrow';
        arrow.textContent = sortKey === col.key ? (sortDir === 'asc' ? ` ${unicodeList.sort_asc}` : ` ${unicodeList.sort_desc}`) : '';
        th.appendChild(arrow);

        const doSort = () => {
          if (!_ms) return;
          if (_ms.sortKey === col.key) {
            _ms.sortDir = _ms.sortDir === 'asc' ? 'desc' : 'asc';
          } else {
            _ms.sortKey = col.key;
            _ms.sortDir = col.key === 'duration' ? 'desc' : 'asc';
          }
          _ms.currentPage = 1;
          _rerender();
        };

        th.addEventListener('click', doSort);
        th.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); doSort(); }
        });
        headerRow.appendChild(th);
      }

      headerRow.addEventListener('keydown', (e) => {
        if (e.target !== headerRow) return;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
          e.preventDefault();
          const ths = [...headerRow.querySelectorAll('.playtime-sort-th')];
          const target = e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? ths[ths.length - 1] : ths[0];
          target?.focus();
        }
      });

      headerRow.addEventListener('keydown', (e) => {
        if (!e.target.classList.contains('playtime-sort-th')) return;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
          e.preventDefault();
          const ths = [...headerRow.querySelectorAll('.playtime-sort-th')];
          const idx = ths.indexOf(e.target);
          const delta = (e.key === 'ArrowLeft' || e.key === 'ArrowUp') ? -1 : 1;
          const next = ths[(idx + delta + ths.length) % ths.length];
          next?.focus();
        }
        // Escape / Tab: return focus to the row itself
        if (e.key === 'Escape') {
          e.preventDefault();
          headerRow.focus();
        }
      });

      thead.appendChild(headerRow);
      table.appendChild(thead);

      const tbody = document.createElement('tbody');

      for (const row of pageItems) {
        const tr = document.createElement('tr');
        if (row._live) tr.className = 'playtime-live-tr';

        const tdDate = document.createElement('td');
        if (row._live) {
          const liveDot = document.createElement('span');
          liveDot.className = 'playtime-live-indicator';
          liveDot.textContent = '▶';
          tdDate.appendChild(liveDot);
          tdDate.append(` ${t('settings.playtime.detail.nowLive')}`);
        } else {
          tdDate.textContent = fmtDateTime(row.started_at);
        }
        tr.appendChild(tdDate);

        const tdVer = document.createElement('td');
        tdVer.textContent = row.version;
        tr.appendChild(tdVer);

        const tdDur = document.createElement('td');
        tdDur.textContent = row.duration_formatted;
        tr.appendChild(tdDur);

        const tdLoader = document.createElement('td');
        if (row.loader) {
          const badge = document.createElement('span');
          badge.className = 'playtime-detail-loader-badge';
          badge.textContent = row.loader.charAt(0).toUpperCase() + row.loader.slice(1);
          tdLoader.appendChild(badge);
        } else {
          const dash = document.createElement('span');
          dash.className = 'playtime-detail-no-loader';
          dash.textContent = unicodeList.empty;
          tdLoader.appendChild(dash);
        }
        tr.appendChild(tdLoader);

        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      listEl.appendChild(table);

      // Restore focus after rebuild.
      if (focusedColKey) {
        const newTh = listEl.querySelector(`.playtime-sort-th[data-col-key="${focusedColKey}"]`);
        if (newTh) newTh.focus({ preventScroll: true });
      } else if (focusedIsRow) {
        const newRow = listEl.querySelector('thead tr');
        if (newRow) newRow.focus({ preventScroll: true });
      }
    }
  }

  // ---- rebuild pagination ----
  const paginationEl = document.getElementById('playtime-detail-pagination');
  if (paginationEl) {
    renderCommonPagination(paginationEl, totalPages, _ms.currentPage, (page) => {
      if (_ms) {
        _ms.currentPage = page;
        _rerender();
      }
    });
  }
};

export const showPlaytimeDetailModal = async () => {
  let res;
  try {
    res = await api('/api/playtime/sessions', 'POST', {});
  } catch (e) {
    showMessageBox({
      title: t('settings.playtime.detail.title'),
      message: `<p style="color:var(--color-error)">${escapeInfoHtml(String(e?.message || t('common.error')))}</p>`,
      buttons: [{ label: t('common.close') }],
      boxClassList: ['playtime-detail-dialog'],
    });
    return;
  }

  if (!res?.ok) {
    showMessageBox({
      title: t('settings.playtime.detail.title'),
      message: `<p style="color:var(--color-error)">${escapeInfoHtml(t('common.error'))}</p>`,
      buttons: [{ label: t('common.close') }],
      boxClassList: ['playtime-detail-dialog'],
    });
    return;
  }

  const { sessions, versions, total } = res;

  // Collect unique loaders from sessions
  const loaderSet = new Set();
  let hasNoLoader = false;
  for (const s of sessions) {
    if (s.loader) loaderSet.add(s.loader);
    else hasNoLoader = true;
  }
  const loaders = [...loaderSet].sort();

  _ms = {
    sessions,
    total: typeof total === 'number' ? total : sessions.length,
    versionFilter: '__all__',
    loaderFilter: '__all__',
    sortKey: 'date',
    sortDir: 'desc',
    currentPage: 1,
    eventSource: null,
    liveSession: null,
    wasPlaying: false,
  };

  const wrap = document.createElement('div');
  wrap.className = 'playtime-detail-wrap';

  const nowPlayingRow = document.createElement('div');
  nowPlayingRow.id = 'playtime-detail-now-playing';
  nowPlayingRow.className = 'playtime-detail-now-playing hidden';
  const npDot = document.createElement('span');
  npDot.className = 'playtime-now-playing-dot';
  npDot.textContent = '▶';
  const npText = document.createElement('span');
  npText.id = 'playtime-detail-now-playing-text';
  npText.textContent = '';
  nowPlayingRow.appendChild(npDot);
  nowPlayingRow.appendChild(npText);
  wrap.appendChild(nowPlayingRow);

  const filterRow = document.createElement('div');
  filterRow.className = 'playtime-detail-filter-row';

  const verLabel = document.createElement('label');
  verLabel.htmlFor = 'playtime-detail-ver-sel';
  verLabel.textContent = t('settings.playtime.detail.filterBy');
  filterRow.appendChild(verLabel);

  const verSel = document.createElement('select');
  verSel.id = 'playtime-detail-ver-sel';
  const allVerOpt = document.createElement('option');
  allVerOpt.value = '__all__';
  allVerOpt.textContent = t('settings.playtime.detail.allVersions');
  verSel.appendChild(allVerOpt);
  for (const v of versions) {
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = v;
    verSel.appendChild(opt);
  }
  verSel.addEventListener('change', () => {
    if (_ms) { _ms.versionFilter = verSel.value; _ms.currentPage = 1; _rerender(); }
  });
  filterRow.appendChild(verSel);

  if (loaders.length > 0 || hasNoLoader) {
    const loaderLabel = document.createElement('label');
    loaderLabel.htmlFor = 'playtime-detail-loader-sel';
    loaderLabel.textContent = t('settings.playtime.detail.loaderFilterBy');
    filterRow.appendChild(loaderLabel);

    const loaderSel = document.createElement('select');
    loaderSel.id = 'playtime-detail-loader-sel';
    const allLoaderOpt = document.createElement('option');
    allLoaderOpt.value = '__all__';
    allLoaderOpt.textContent = t('settings.playtime.detail.allModloaders');
    loaderSel.appendChild(allLoaderOpt);
    for (const l of loaders) {
      const opt = document.createElement('option');
      opt.value = l;
      opt.textContent = l.charAt(0).toUpperCase() + l.slice(1);
      loaderSel.appendChild(opt);
    }
    if (hasNoLoader) {
      const opt = document.createElement('option');
      opt.value = '__none__';
      opt.textContent = t('settings.playtime.detail.noLoader');
      loaderSel.appendChild(opt);
    }
    loaderSel.addEventListener('change', () => {
      if (_ms) { _ms.loaderFilter = loaderSel.value; _ms.currentPage = 1; _rerender(); }
    });
    filterRow.appendChild(loaderSel);
  }

  wrap.appendChild(filterRow);

  // ---- Total row ----
  const totalRow = document.createElement('div');
  totalRow.className = 'playtime-detail-total-row';
  const totalLabel = document.createElement('span');
  totalLabel.className = 'playtime-detail-total-label';
  totalLabel.textContent = t('settings.playtime.detail.totalLabel');
  const totalVal = document.createElement('span');
  totalVal.id = 'playtime-detail-total-val';
  totalVal.className = 'playtime-detail-total-val';
  totalRow.appendChild(totalLabel);
  totalRow.appendChild(totalVal);
  wrap.appendChild(totalRow);

  // ---- List container ----
  const listEl = document.createElement('div');
  listEl.id = 'playtime-detail-list';
  listEl.className = 'playtime-detail-list';
  wrap.appendChild(listEl);

  // ---- Pagination container ----
  const paginationEl = document.createElement('div');
  paginationEl.id = 'playtime-detail-pagination';
  paginationEl.className = 'mods-pagination';
  wrap.appendChild(paginationEl);

  // ---- Truncation notice (shown when server capped the returned sessions) ----
  const truncEl = document.createElement('p');
  truncEl.id = 'playtime-detail-trunc';
  truncEl.className = 'playtime-detail-trunc hidden';
  wrap.appendChild(truncEl);

  showMessageBox({
    title: t('settings.playtime.detail.title'),
    customContent: wrap,
    buttons: [{ label: t('common.close') }],
    boxClassList: ['playtime-detail-dialog'],
    onClose: () => {
      if (_ms && _ms.eventSource) {
        _ms.eventSource.close();
      }
      _ms = null;
    },
  });

  setTimeout(() => {
    _rerender();

    // ---- Start SSE live stream ----
    try {
      if (_ms && _ms.eventSource) {
        try { _ms.eventSource.close(); } catch (_) { /* ignore */ }
        _ms.eventSource = null;
      }
      const es = new EventSource('/api/stream/playtime-live');
      if (_ms) _ms.eventSource = es;

      es.onmessage = (event) => {
        if (!_ms) { es.close(); return; }
        let data;
        try { data = JSON.parse(event.data); } catch (_) { return; }

        // Update Now Playing banner
        const row = document.getElementById('playtime-detail-now-playing');
        const text = document.getElementById('playtime-detail-now-playing-text');
        if (row && text) {
          if (data.playing) {
            const loaderPart = data.loader ? ` · ${data.loader}` : '';
            text.textContent = `${data.version}${loaderPart} — ${data.elapsed_formatted}`;
            row.classList.remove('hidden');
          } else {
            row.classList.add('hidden');
          }
        }

        // Update live session row in table
        const wasPlaying = _ms.wasPlaying;
        if (data.playing) {
          _ms.wasPlaying = true;
          _ms.liveSession = {
            started_at: Math.floor(Date.now() / 1000) - Math.floor(data.elapsed_s || 0),
            version: data.version,
            duration_formatted: data.elapsed_formatted,
            duration_s: data.elapsed_s,
            loader: data.loader || null,
            _live: true,
          };
          _rerender();
        } else {
          _ms.wasPlaying = false;
          _ms.liveSession = null;
          if (wasPlaying) {
            // Session just ended — refresh from server so the new completed session appears
            api('/api/playtime/sessions', 'POST', {}).then((res) => {
              if (!_ms || !res?.ok) return;
              _ms.sessions = res.sessions;
              _rerender();
            }).catch(() => { if (_ms) _rerender(); });
          } else {
            _rerender();
          }
        }
      };

      es.onerror = () => { es.close(); if (_ms) _ms.eventSource = null; };
    } catch (_) { /* EventSource not supported */ }
  }, 50);
};
