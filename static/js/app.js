/* =====================================================
   PATHWAYS TO POSITIONS — app.js
   SBCUSD high schools ←→ County of San Bernardino entry-level
   classifications, on an interactive map.

   Three-column flow:
     [LEFT]   School + clickable pathway list
     [CENTER] Interactive map (filterable by County CTE program)
     [RIGHT]  County positions (MQ, pay band, ladder, Hiring-now pill)

   Driven entirely client-side from a small set of JSON endpoints.
   ===================================================== */

'use strict';

// ── Short labels for the 10 County CTE programs (chip text) ──
const PROGRAM_SHORT = {
  "Automotive":                                         "Automotive",
  "Arts, Media & Entertainment":                        "Arts/Media",
  "Business":                                           "Business",
  "Patient Care":                                       "Patient Care",
  "Building & Construction":                            "Construction",
  "Education, Child Development & Family Services":     "Education/Family",
  "Energy, Environment & Utilities":                    "Environment",
  "Hospitality, Tourism & Recreation":                  "Hospitality",
  "Information & Communication Technologies":           "ICT",
  "Public Service":                                     "Public Service",
};

// ── Global state ──────────────────────────────────────
const state = {
  schools:           [],   // [{id, name, district, lat, lng, pathway_ids, program_ids}]
  programs:          [],   // [{id, name, position_count, display_order}]
  pathways:          [],   // [{id, name, sector}]
  refreshStatus:     null, // {last_refresh, positions_hiring, per_program:[...]}
  hiringProgramIds:  new Set(),
  selectedSchool:    null,
  selectedPathwayId: null,
  selectedProgramId: null,
  map:               null,
  cluster:           null,
  markers:           [],
};

// ── DOM refs ──────────────────────────────────────────
const el = {
  chipBar:          document.getElementById('chip-bar'),
  headerStats:      document.getElementById('header-stats'),

  leftEmpty:        document.getElementById('left-empty'),
  leftSchool:       document.getElementById('left-school'),
  leftSchoolName:   document.getElementById('left-school-name'),
  leftSchoolDist:   document.getElementById('left-school-district'),
  leftPathways:     document.getElementById('left-pathways'),

  rightEmpty:       document.getElementById('right-empty'),
  rightPositions:   document.getElementById('right-positions'),

  statSchool:       document.getElementById('stat-school'),
  statProgram:      document.getElementById('stat-program'),
  statCount:        document.getElementById('stat-count'),
  statPay:          document.getElementById('stat-pay'),

  footerRefresh:    document.getElementById('footer-refresh'),
};

// ── Utilities ─────────────────────────────────────────
function show(elem) { elem.hidden = false; }
function hide(elem) { elem.hidden = true;  }

async function apiFetch(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API error ${res.status} at ${url}`);
  return res.json();
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ── Bootstrap ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  initMap();
  await Promise.all([
    loadSchoolsFull(),
    loadPrograms(),
    loadPathways(),
    loadRefreshStatus(),
  ]);
  renderHeaderStats();
  renderProgramChips();
  renderFooterRefresh();
  renderMarkers();
  fitMapToSchools();
});

// =====================================================
//   MAP
// =====================================================

function initMap() {
  state.map = L.map('map', { zoomControl: true }).setView([34.138, -117.275], 12);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(state.map);
  state.cluster = L.markerClusterGroup({
    showCoverageOnHover: false,
    spiderfyOnMaxZoom:   true,
    maxClusterRadius:    32,
  });
  state.map.addLayer(state.cluster);
}

function fitMapToSchools() {
  const pts = state.schools
    .filter(s => s.latitude && s.longitude)
    .map(s => [s.latitude, s.longitude]);
  if (pts.length === 0) return;
  state.map.fitBounds(pts, { padding: [30, 30], maxZoom: 13 });
}

// Marker icon variants. The "ring" property layers a thin gold ring around a
// marker that has any position currently hiring on that school's programs —
// this is what makes the map convey live hiring data at a glance.
function makeIcon({ size, color, ring = null }) {
  const ringHtml = ring
    ? `<div style="position:absolute;inset:-4px;border:2px solid ${ring};border-radius:999px;pointer-events:none;"></div>`
    : '';
  return L.divIcon({
    className: '',
    html: `<div style="position:relative;width:${size}px;height:${size}px;">
      ${ringHtml}
      <div style="
        position:absolute;inset:0;
        background:${color};
        border:2.5px solid #fff;
        border-radius:50%;
        box-shadow:0 2px 5px rgba(0,0,0,.32);
      "></div>
    </div>`,
    iconSize:   [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

const ICON = {
  default:  hiring => makeIcon({ size: 14, color: '#6e1527', ring: hiring ? '#1a7a3a' : null }),
  match:    hiring => makeIcon({ size: 16, color: '#6e1527', ring: hiring ? '#1a7a3a' : null }),
  dim:      ()     => makeIcon({ size: 10, color: '#cfd5dc' }),
  selected: hiring => makeIcon({ size: 20, color: '#d4a012', ring: hiring ? '#1a7a3a' : null }),
};

function schoolMatchesProgramFilter(s) {
  if (!state.selectedProgramId) return true;
  return s.program_ids.includes(state.selectedProgramId);
}

function schoolIsHiring(s) {
  return s.program_ids.some(pid => state.hiringProgramIds.has(pid));
}

function renderMarkers() {
  state.cluster.clearLayers();
  state.markers = [];

  state.schools.forEach(school => {
    if (!school.latitude || !school.longitude) return;
    const matches    = schoolMatchesProgramFilter(school);
    const hiring     = schoolIsHiring(school);
    const isSelected = state.selectedSchool && state.selectedSchool.id === school.id;
    const filtering  = !!state.selectedProgramId;

    let icon;
    if (isSelected)           icon = ICON.selected(hiring);
    else if (!filtering)      icon = ICON.default(hiring);
    else if (matches)         icon = ICON.match(hiring);
    else                      icon = ICON.dim();

    const opacity = filtering && !matches && !isSelected ? 0.5 : 1;
    const marker = L.marker([school.latitude, school.longitude], {
      icon, opacity, title: school.name,
    });
    const progSummary = school.program_ids
      .map(pid => (state.programs.find(p => p.id === pid) || {}).name)
      .filter(Boolean)
      .map(escapeHtml)
      .join(', ');
    marker.bindPopup(`
      <div style="font-family:'DM Sans',system-ui,sans-serif;min-width:200px;">
        <strong style="color:#6e1527;font-size:14px;">${escapeHtml(school.name)}</strong><br>
        <span style="font-size:11px;color:#6b6b76;">${escapeHtml(school.district)}</span><br>
        <span style="font-size:11px;color:#1a1a1e;margin-top:4px;display:inline-block;">
          ${school.pathway_count} pathway${school.pathway_count !== 1 ? 's' : ''}
        </span>
        ${progSummary ? `<div style="font-size:10px;color:#6b6b76;margin-top:2px;">${progSummary}</div>` : ''}
        ${hiring ? '<div style="margin-top:4px;color:#1a7a3a;font-weight:700;font-size:11px;">● Has positions hiring now</div>' : ''}
      </div>
    `);
    marker.on('click', () => selectSchool(school));
    state.cluster.addLayer(marker);
    state.markers.push({ schoolId: school.id, marker });
  });
}

// =====================================================
//   HEADER STATS + FOOTER REFRESH
// =====================================================

function renderHeaderStats() {
  const positionCount = state.programs.reduce((sum, p) => sum + (p.position_count || 0), 0);
  el.headerStats.innerHTML = `
    <div class="p2p-stat">
      <div class="p2p-stat-n">${state.schools.length}</div>
      <div class="p2p-stat-l">SBCUSD Schools</div>
    </div>
    <div class="p2p-stat">
      <div class="p2p-stat-n">${state.programs.length}</div>
      <div class="p2p-stat-l">CTE Programs</div>
    </div>
    <div class="p2p-stat">
      <div class="p2p-stat-n">${positionCount}</div>
      <div class="p2p-stat-l">County Positions</div>
    </div>
    ${state.refreshStatus && state.refreshStatus.positions_hiring
      ? `<div class="p2p-stat p2p-stat--hiring">
          <div class="p2p-stat-n">${state.refreshStatus.positions_hiring}</div>
          <div class="p2p-stat-l">Hiring now</div>
         </div>`
      : ''}
  `;
}

function renderFooterRefresh() {
  if (!el.footerRefresh) return;
  if (state.refreshStatus && state.refreshStatus.last_refresh) {
    el.footerRefresh.textContent = `Hiring overlay refreshed ${state.refreshStatus.last_refresh} UTC`;
  } else {
    el.footerRefresh.textContent = '';
  }
}

// =====================================================
//   PROGRAM CHIPS
// =====================================================

function renderProgramChips() {
  el.chipBar.innerHTML = '<span class="p2p-chip-label">CTE Programs:</span>';
  state.programs
    .slice()
    .sort((a, b) => a.display_order - b.display_order)
    .forEach(prog => {
      const chip = document.createElement('button');
      chip.className   = 'p2p-chip';
      chip.dataset.pid = prog.id;
      chip.type        = 'button';
      const short = PROGRAM_SHORT[prog.name] || prog.name;
      const hiring = (state.refreshStatus?.per_program || []).find(r => r.id === prog.id);
      chip.innerHTML = `
        <span>${escapeHtml(short)}</span>
        ${hiring && hiring.posting_count
          ? `<span class="p2p-chip-hiring" title="${hiring.posting_count} hiring now">●</span>`
          : ''}
      `;
      chip.addEventListener('click', () => onProgramChipClick(prog));
      el.chipBar.appendChild(chip);
    });
  const reset = document.createElement('button');
  reset.className = 'p2p-chip p2p-chip--reset';
  reset.type      = 'button';
  reset.textContent = 'Reset';
  reset.addEventListener('click', resetAll);
  el.chipBar.appendChild(reset);
}

function onProgramChipClick(prog) {
  // Toggle: clicking the active chip clears the filter
  if (state.selectedProgramId === prog.id) {
    state.selectedProgramId = null;
  } else {
    state.selectedProgramId = prog.id;
  }
  refreshChipActiveStates();

  // When activating a program, focus the map on schools that offer it AND
  // auto-select the first such school so the side panels populate.
  if (state.selectedProgramId) {
    const matches = state.schools.filter(schoolMatchesProgramFilter);
    if (matches.length) {
      // Auto-select first matching school + preferentially auto-pick a pathway
      // from this program if the school has one.
      selectSchool(matches[0], { preferredProgramId: state.selectedProgramId });
      const pts = matches
        .filter(s => s.latitude && s.longitude)
        .map(s => [s.latitude, s.longitude]);
      if (pts.length) {
        state.map.fitBounds(pts, { padding: [40, 40], maxZoom: 14 });
      }
    }
  }
  renderMarkers();
}

function refreshChipActiveStates() {
  el.chipBar.querySelectorAll('.p2p-chip').forEach(c => {
    if (c.classList.contains('p2p-chip--reset')) return;
    c.classList.toggle('p2p-chip--active', parseInt(c.dataset.pid) === state.selectedProgramId);
  });
}

// =====================================================
//   SCHOOL SELECTION + LEFT PANEL
// =====================================================

function selectSchool(school, { preferredProgramId = null } = {}) {
  state.selectedSchool = school;
  hide(el.leftEmpty);
  show(el.leftSchool);

  el.leftSchoolName.textContent = school.name;
  el.leftSchoolDist.textContent = school.district;

  // Group pathways by sector
  const offered = school.pathway_ids
    .map(pid => state.pathways.find(p => p.id === pid))
    .filter(Boolean);
  const bySector = {};
  offered.forEach(p => {
    const sec = p.sector || 'Other';
    if (!bySector[sec]) bySector[sec] = [];
    bySector[sec].push(p);
  });

  el.leftPathways.innerHTML = '';
  if (offered.length === 0) {
    el.leftPathways.innerHTML = '<p class="p2p-empty">No pathways on file for this school.</p>';
  } else {
    Object.keys(bySector).sort().forEach(sector => {
      const group = document.createElement('div');
      group.className = 'p2p-pathway-group';
      group.innerHTML = `<div class="p2p-pathway-sector">${escapeHtml(sector)}</div>`;
      bySector[sector].forEach(pw => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'p2p-pathway';
        btn.dataset.pid = pw.id;
        // A pathway is "hiring" if its tied county program has any current
        // posting. Same rule as the program chips and the map markers — the
        // overlay flows down to the leaf interaction.
        const isHiring = pw.cte_program_id && state.hiringProgramIds.has(pw.cte_program_id);
        btn.innerHTML = `
          <span class="p2p-pathway-name">${escapeHtml(pw.name)}</span>
          ${isHiring ? '<span class="p2p-pathway-hiring" title="Has a position hiring now">●</span>' : ''}
          ${pw.cte_program_id === null
            ? '<span class="p2p-pathway-untied" title="No county program tied to this pathway yet">○</span>'
            : ''}
        `;
        btn.addEventListener('click', () => onPathwayClick(pw));
        group.appendChild(btn);
      });
      el.leftPathways.appendChild(group);
    });
  }

  // Mark pathways that belong to the active program filter so the user can see
  // which of the school's pathways tie to the clicked CTE program chip.
  if (preferredProgramId) {
    el.leftPathways.querySelectorAll('.p2p-pathway').forEach(btn => {
      const pid = parseInt(btn.dataset.pid);
      const pw = state.pathways.find(x => x.id === pid);
      if (pw && pw.cte_program_id === preferredProgramId) {
        btn.classList.add('p2p-pathway--in-program');
      }
    });
    // Auto-select the first pathway at this school that actually belongs to the
    // chip's CTE program — not just any pathway.
    const candidate = offered.find(p => p.cte_program_id === preferredProgramId);
    if (candidate) onPathwayClick(candidate);
    else            clearRightPanel();
  } else {
    clearRightPanel();
  }

  renderMarkers();
  // Only zoom in on direct map-marker clicks; chip-driven selections already
  // fitBounds to the matching school set in onProgramChipClick.
  if (!preferredProgramId && school.latitude && school.longitude) {
    state.map.setView([school.latitude, school.longitude], Math.max(state.map.getZoom(), 14));
  }
}

// =====================================================
//   PATHWAY CLICK → RIGHT PANEL
// =====================================================

async function onPathwayClick(pathway) {
  state.selectedPathwayId = pathway.id;
  document.querySelectorAll('.p2p-pathway').forEach(b => {
    b.classList.toggle('p2p-pathway--active', parseInt(b.dataset.pid) === pathway.id);
  });

  hide(el.rightEmpty);
  el.rightPositions.innerHTML = '<div class="p2p-loading">Loading positions…</div>';
  el.statSchool.textContent  = state.selectedSchool ? state.selectedSchool.name : '—';
  el.statProgram.textContent = '…';
  el.statCount.textContent   = '…';
  el.statPay.textContent     = '…';

  try {
    const data = await apiFetch(`/api/jobs?pathway_id=${pathway.id}`);
    if (!data.program) {
      el.rightPositions.innerHTML = `
        <div class="p2p-empty">
          This pathway is not currently tied to one of the County's 10 CTE programs.
          Speak with your counselor for guidance.
        </div>`;
      el.statProgram.textContent = '—';
      el.statCount.textContent   = '0';
      el.statPay.textContent     = '—';
      return;
    }
    el.statProgram.textContent = data.program.name;
    el.statCount.textContent   = data.positions.length;
    const pays = data.positions
      .filter(p => p.min_hourly && p.max_hourly)
      .reduce(
        (acc, p) => ({
          lo: Math.min(acc.lo, p.min_hourly),
          hi: Math.max(acc.hi, p.max_hourly),
        }),
        { lo: Infinity, hi: -Infinity }
      );
    el.statPay.textContent = pays.lo === Infinity
      ? 'TBD'
      : `$${pays.lo.toFixed(2)} – $${pays.hi.toFixed(2)}/hr`;
    renderPositions(data.positions);
  } catch (e) {
    console.error('Failed to load positions:', e);
    el.rightPositions.innerHTML =
      '<div class="p2p-empty p2p-empty--err">Could not load county positions. Try again later.</div>';
  }
}

function clearRightPanel() {
  state.selectedPathwayId = null;
  show(el.rightEmpty);
  el.rightPositions.innerHTML = '';
  el.statSchool.textContent  = state.selectedSchool ? state.selectedSchool.name : '—';
  el.statProgram.textContent = '—';
  el.statCount.textContent   = '0';
  el.statPay.textContent     = '—';
}

function renderPositions(positions) {
  el.rightPositions.innerHTML = '';
  if (!positions.length) {
    el.rightPositions.innerHTML = '<div class="p2p-empty">No positions tied to this pathway yet.</div>';
    return;
  }
  positions.forEach((pos, i) => {
    const card = document.createElement('div');
    card.className = 'p2p-pos';
    if (pos.is_hiring_now)      card.classList.add('p2p-pos--hiring');
    if (pos.job_code === 'NEW') card.classList.add('p2p-pos--new');
    card.style.animationDelay = `${i * 0.04}s`;

    const codeBadge = pos.job_code
      ? `<span class="p2p-pos-code">${escapeHtml(pos.job_code)}${pos.job_code === 'NEW' ? ' · Proposed' : ''}</span>`
      : '';

    const hiringPill = pos.is_hiring_now
      ? `<span class="p2p-pos-hiring">● Hiring now${pos.current_postings.length > 1 ? ' · ' + pos.current_postings.length : ''}</span>`
      : '';

    const salary = (pos.min_hourly && pos.max_hourly)
      ? `<span class="p2p-pos-salary">$${pos.min_hourly.toFixed(2)} – $${pos.max_hourly.toFixed(2)}/hr</span>`
      : '<span class="p2p-pos-salary p2p-pos-salary--tbd">TBD</span>';

    const liveUrl  = pos.is_hiring_now && pos.current_postings[0]?.url;
    const applyHref = liveUrl || pos.apply_url;
    const applyLabel = pos.is_hiring_now
      ? 'Apply now ↗'
      : (pos.apply_url ? 'View posting ↗' : 'Not yet posting');
    const applyBtn = applyHref
      ? `<a class="p2p-pos-apply" href="${escapeHtml(applyHref)}" target="_blank" rel="noopener noreferrer">${applyLabel}</a>`
      : `<span class="p2p-pos-apply p2p-pos-apply--disabled">${applyLabel}</span>`;

    const ladderHtml = (pos.ladder && pos.ladder.length > 1)
      ? `<div class="p2p-pos-ladder">↗ ${pos.ladder.map(s => escapeHtml(s.title)).join(' → ')}</div>`
      : '';

    const mqsHtml = pos.mqs_text
      ? `<details class="p2p-pos-mqs">
          <summary>Minimum qualifications</summary>
          <pre>${escapeHtml(pos.mqs_text)}</pre>
        </details>`
      : '';

    card.innerHTML = `
      <div class="p2p-pos-head">
        <h3>${escapeHtml(pos.title)}</h3>
        ${hiringPill}
      </div>
      <div class="p2p-pos-meta">
        ${codeBadge}
        ${salary}
      </div>
      ${ladderHtml}
      ${mqsHtml}
      <div class="p2p-pos-foot">
        ${applyBtn}
      </div>
    `;
    el.rightPositions.appendChild(card);
  });
}

// =====================================================
//   RESET
// =====================================================

function resetAll() {
  state.selectedProgramId = null;
  state.selectedSchool    = null;
  state.selectedPathwayId = null;
  refreshChipActiveStates();
  hide(el.leftSchool);
  show(el.leftEmpty);
  el.leftPathways.innerHTML = '';
  clearRightPanel();
  renderMarkers();
  fitMapToSchools();
}

// =====================================================
//   DATA LOADING
// =====================================================

async function loadSchoolsFull() {
  try {
    state.schools = await apiFetch('/api/schools/full');
  } catch (e) {
    console.error('Failed to load schools:', e);
    state.schools = [];
  }
}

async function loadPrograms() {
  try {
    state.programs = await apiFetch('/api/programs');
  } catch (e) {
    console.error('Failed to load programs:', e);
    state.programs = [];
  }
}

async function loadPathways() {
  try {
    state.pathways = await apiFetch('/api/pathways');
  } catch (e) {
    console.error('Failed to load pathways:', e);
    state.pathways = [];
  }
}

async function loadRefreshStatus() {
  try {
    state.refreshStatus = await apiFetch('/api/refresh-status');
    state.hiringProgramIds = new Set(
      (state.refreshStatus.per_program || [])
        .filter(r => r.posting_count > 0)
        .map(r => r.id)
    );
  } catch (e) {
    console.warn('No refresh status available:', e);
    state.refreshStatus = null;
  }
}
