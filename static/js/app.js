/* =====================================================
   PATHWAYS TO POSITIONS — app.js
   Full-bleed GIS dashboard of SBCUSD high schools and the
   County entry-level classifications tied to each CTE pathway.

   Map fills the viewport. School & Pathways drawer slides in
   from the left when a school is selected. County Positions
   drawer slides in from the right when a pathway is picked.
   Marker color encodes the school's primary CTE program;
   green ring = at least one entry classification hiring now.
   Hiring-density heatmap and SBCUSD boundary polygon are
   toggleable layers (top-right widget).
   ===================================================== */

'use strict';

// ── 10-color categorical palette for the County CTE programs.
//    Chosen for visual separation on a desaturated basemap and
//    OK contrast against white marker borders.
const PROGRAM_PALETTE = {
  1:  '#5e6f8a',   // Automotive            — slate blue
  2:  '#9467bd',   // Arts, Media & Ent.    — purple
  3:  '#17becf',   // Business              — cyan
  4:  '#d62728',   // Patient Care          — red
  5:  '#8c564b',   // Building & Construc.  — brown
  6:  '#e377c2',   // Education / Family    — pink
  7:  '#2ca02c',   // Energy, Env, Util.    — green
  8:  '#ff7f0e',   // Hospitality           — orange
  9:  '#1a4f8a',   // ICT                   — navy
  10: '#d4a012',   // Public Service        — SBCUSD gold
};
const PROGRAM_FALLBACK_COLOR = '#6e1527';   // SBCUSD maroon for "no program tied"

// Short labels for the chip bar.
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

// ── Global state ─────────────────────────────────────
const state = {
  schools:           [],
  programs:          [],
  pathways:          [],
  refreshStatus:     null,
  hiringProgramIds:  new Set(),
  selectedSchool:    null,
  selectedPathwayId: null,
  selectedProgramId: null,
  map:               null,
  cluster:           null,    // L.markerClusterGroup
  markerLayer:       null,    // plain L.layerGroup (when cluster disabled)
  heatLayer:         null,    // L.heatLayer
  boundaryLayer:     null,    // L.polygon
  markers:           [],
  primaryProgramByPositionId: {},  // pre-computed map
};

// ── DOM refs ─────────────────────────────────────────
const el = {
  chipBar:         document.getElementById('chip-bar'),
  headerStats:     document.getElementById('header-stats'),
  legendGrid:      document.getElementById('legend-grid'),
  footerRefresh:   document.getElementById('footer-refresh'),

  toggleBoundary:  document.getElementById('toggle-boundary'),
  toggleHeatmap:   document.getElementById('toggle-heatmap'),
  toggleCluster:   document.getElementById('toggle-cluster'),

  leftDrawer:      document.getElementById('left-drawer'),
  leftDrawerTab:   document.getElementById('left-drawer-tab'),
  leftEmpty:       document.getElementById('left-empty'),
  leftSchool:      document.getElementById('left-school'),
  leftSchoolName:  document.getElementById('left-school-name'),
  leftSchoolDist:  document.getElementById('left-school-district'),
  leftSchoolPrimary: document.getElementById('left-school-primary'),
  leftPathways:    document.getElementById('left-pathways'),

  rightDrawer:     document.getElementById('right-drawer'),
  rightDrawerTab:  document.getElementById('right-drawer-tab'),
  rightEmpty:      document.getElementById('right-empty'),
  rightPositions:  document.getElementById('right-positions'),

  statSchool:      document.getElementById('stat-school'),
  statProgram:     document.getElementById('stat-program'),
  statCount:       document.getElementById('stat-count'),
  statPay:         document.getElementById('stat-pay'),
};

// ── Utilities ────────────────────────────────────────
// apiFetch is dual-mode: when window.P2P_STATIC_BASE is set (GitHub Pages
// build), it rewrites /api/* URLs to pre-baked /data/*.json paths. Otherwise
// it hits the live Flask backend at /api/*.
function staticUrlFor(apiUrl, base) {
  let m;
  if (apiUrl === '/api/schools/full')      return `${base}/data/schools-full.json`;
  if (apiUrl === '/api/schools')           return `${base}/data/schools.json`;
  if ((m = apiUrl.match(/^\/api\/schools\/(\d+)\/pathways$/)))
                                           return `${base}/data/schools/${m[1]}-pathways.json`;
  if (apiUrl === '/api/programs')          return `${base}/data/programs.json`;
  if ((m = apiUrl.match(/^\/api\/programs\/(\d+)$/)))
                                           return `${base}/data/programs/${m[1]}.json`;
  if (apiUrl === '/api/pathways')          return `${base}/data/pathways.json`;
  if ((m = apiUrl.match(/^\/api\/jobs\?pathway_id=(\d+)$/)))
                                           return `${base}/data/jobs/${m[1]}.json`;
  if ((m = apiUrl.match(/^\/api\/positions\/(\d+)$/)))
                                           return `${base}/data/positions/${m[1]}.json`;
  if (apiUrl === '/api/careers')           return `${base}/data/careers.json`;
  if (apiUrl === '/api/refresh-status')    return `${base}/data/refresh-status.json`;
  return apiUrl;
}

async function apiFetch(url) {
  const base = window.P2P_STATIC_BASE;
  const realUrl = base ? staticUrlFor(url, base) : url;
  const res = await fetch(realUrl);
  if (!res.ok) throw new Error(`API error ${res.status} at ${realUrl}`);
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

function openDrawer(which) {
  (which === 'left' ? el.leftDrawer : el.rightDrawer).classList.add('p2p-drawer--open');
  const tab = which === 'left' ? el.leftDrawerTab : el.rightDrawerTab;
  tab.setAttribute('aria-expanded', 'true');
}
function closeDrawer(which) {
  (which === 'left' ? el.leftDrawer : el.rightDrawer).classList.remove('p2p-drawer--open');
  const tab = which === 'left' ? el.leftDrawerTab : el.rightDrawerTab;
  tab.setAttribute('aria-expanded', 'false');
}
function toggleDrawer(which) {
  const d = which === 'left' ? el.leftDrawer : el.rightDrawer;
  if (d.classList.contains('p2p-drawer--open')) closeDrawer(which);
  else                                          openDrawer(which);
}

// ── Bootstrap ────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  initMap();
  bindEvents();
  await Promise.all([
    loadSchoolsFull(),
    loadPrograms(),
    loadPathways(),
    loadRefreshStatus(),
  ]);
  renderHeaderStats();
  renderProgramChips();
  renderLegend();
  renderFooterRefresh();
  drawBoundary();
  renderMarkers();
  renderHeatmap();
  fitMapToSchools();
});

// =====================================================
//   MAP
// =====================================================

function initMap() {
  state.map = L.map('map', {
    zoomControl: true,
    attributionControl: true,
  }).setView([34.138, -117.275], 12);

  // Light/desaturated CARTO basemap reads better as a data layer base than
  // standard OSM. Falls back to OSM via the tile layer's error handler.
  L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · © <a href="https://carto.com/attributions">CARTO</a>',
      maxZoom: 19,
      subdomains: 'abcd',
    }
  ).addTo(state.map);

  // Move zoom control into the bottom-left so it doesn't overlap the brand widget.
  state.map.zoomControl.setPosition('bottomleft');

  state.cluster = L.markerClusterGroup({
    showCoverageOnHover: false,
    spiderfyOnMaxZoom:   true,
    maxClusterRadius:    32,
  });
  state.markerLayer = L.layerGroup();
  state.map.addLayer(state.cluster);
}

function fitMapToSchools() {
  const pts = state.schools
    .filter(s => s.latitude && s.longitude)
    .map(s => [s.latitude, s.longitude]);
  if (pts.length === 0) return;
  state.map.fitBounds(pts, { padding: [60, 60], maxZoom: 13 });
}

// ── primary program for each school = the program with the most
//    pathways at that school. Tie-breaker by program display_order.
function schoolPrimaryProgramId(school) {
  if (!school.pathway_ids || !school.pathway_ids.length) return null;
  const counts = {};
  school.pathway_ids.forEach(pid => {
    const pw = state.pathways.find(x => x.id === pid);
    if (pw && pw.cte_program_id) {
      counts[pw.cte_program_id] = (counts[pw.cte_program_id] || 0) + 1;
    }
  });
  const ids = Object.keys(counts);
  if (!ids.length) return null;
  ids.sort((a, b) => {
    const dc = counts[b] - counts[a];
    if (dc !== 0) return dc;
    const pa = state.programs.find(p => p.id === parseInt(a));
    const pb = state.programs.find(p => p.id === parseInt(b));
    return (pa?.display_order || 99) - (pb?.display_order || 99);
  });
  return parseInt(ids[0]);
}

function programColor(programId) {
  return PROGRAM_PALETTE[programId] || PROGRAM_FALLBACK_COLOR;
}

function schoolIsHiring(s) {
  return s.program_ids.some(pid => state.hiringProgramIds.has(pid));
}

function makeProgramIcon({ size, color, ring = null, isSelected = false }) {
  const ringHtml = ring
    ? `<div style="position:absolute;inset:-5px;border:2px solid ${ring};border-radius:50%;pointer-events:none;"></div>`
    : '';
  const selectedRing = isSelected
    ? `<div style="position:absolute;inset:-9px;border:2px dashed #d4a012;border-radius:50%;pointer-events:none;"></div>`
    : '';
  return L.divIcon({
    className: '',
    html: `<div style="position:relative;width:${size}px;height:${size}px;">
      ${ringHtml}
      ${selectedRing}
      <div style="
        position:absolute;inset:0;
        background:${color};
        border:2px solid #fff;
        border-radius:50%;
        box-shadow:0 2px 6px rgba(0,0,0,.4);
      "></div>
    </div>`,
    iconSize:   [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function renderMarkers() {
  // Active layer is the one currently attached to the map. The cluster toggle
  // swaps which layer .renderMarkers() populates without ever duplicating.
  const useCluster  = el.toggleCluster.checked;
  const targetLayer = useCluster ? state.cluster : state.markerLayer;
  state.cluster.clearLayers();
  state.markerLayer.clearLayers();
  state.markers = [];

  state.schools.forEach(school => {
    if (!school.latitude || !school.longitude) return;
    const matches    = !state.selectedProgramId
                       || school.program_ids.includes(state.selectedProgramId);
    const isSelected = state.selectedSchool && state.selectedSchool.id === school.id;
    const hiring     = schoolIsHiring(school);

    const primary = schoolPrimaryProgramId(school);
    const color   = matches ? programColor(primary) : '#cfd5dc';
    const size    = isSelected ? 22 : (matches ? 16 : 11);
    const ring    = hiring && matches ? '#1a7a3a' : null;

    const icon = makeProgramIcon({ size, color, ring, isSelected });
    const opacity = (!matches && !isSelected) ? 0.55 : 1;
    const marker = L.marker([school.latitude, school.longitude], {
      icon, opacity, title: school.name,
    });

    const programNames = school.program_ids
      .map(pid => (state.programs.find(p => p.id === pid) || {}).name)
      .filter(Boolean);
    const primaryName = primary
      ? (state.programs.find(p => p.id === primary) || {}).name
      : null;

    marker.bindPopup(`
      <div style="font-family:'DM Sans',system-ui,sans-serif;min-width:200px;">
        <strong style="color:#6e1527;font-size:14px;">${escapeHtml(school.name)}</strong><br>
        <span style="font-size:11px;color:#6b6b76;">${escapeHtml(school.district)}</span><br>
        <div style="margin-top:5px;font-size:11px;color:#1a1a1e;">
          <strong>${school.pathway_count}</strong> pathway${school.pathway_count !== 1 ? 's' : ''}
          across <strong>${programNames.length}</strong> county program${programNames.length === 1 ? '' : 's'}
        </div>
        ${primaryName ? `<div style="font-size:11px;color:${programColor(primary)};font-weight:600;margin-top:2px;">Primary: ${escapeHtml(primaryName)}</div>` : ''}
        ${hiring ? '<div style="margin-top:5px;color:#1a7a3a;font-weight:700;font-size:11px;">● Has positions hiring now</div>' : ''}
      </div>
    `);
    marker.on('click', () => selectSchool(school));

    targetLayer.addLayer(marker);
    state.markers.push({ schoolId: school.id, marker });
  });
}

// =====================================================
//   HEATMAP layer (hiring density)
// =====================================================

function renderHeatmap() {
  if (state.heatLayer) {
    state.map.removeLayer(state.heatLayer);
    state.heatLayer = null;
  }
  if (!el.toggleHeatmap.checked) return;

  // Weight each school by how many of its programs have hiring now.
  // No-hiring schools get weight 0 (no heat contribution).
  const points = state.schools
    .filter(s => s.latitude && s.longitude)
    .map(s => {
      const hiringPrograms = s.program_ids.filter(pid => state.hiringProgramIds.has(pid));
      return [s.latitude, s.longitude, Math.max(hiringPrograms.length, 0)];
    })
    .filter(p => p[2] > 0);

  if (!points.length) return;
  // Boost weights so a single hiring program registers strongly at zoom 12–14.
  const boosted = points.map(([lat, lng, w]) => [lat, lng, Math.min(w * 6, 18)]);
  state.heatLayer = L.heatLayer(boosted, {
    radius: 70,
    blur: 50,
    max: 18,
    minOpacity: 0.45,
    gradient: { 0.25: '#fee8c8', 0.55: '#fdbb84', 0.85: '#e34a33' },
  }).addTo(state.map);
}

// =====================================================
//   SBCUSD BOUNDARY polygon (convex hull + buffer)
// =====================================================

function drawBoundary() {
  if (state.boundaryLayer) {
    state.map.removeLayer(state.boundaryLayer);
    state.boundaryLayer = null;
  }
  if (!el.toggleBoundary.checked) return;

  const pts = state.schools
    .filter(s => s.latitude && s.longitude)
    .map(s => [s.latitude, s.longitude]);
  if (pts.length < 3) return;

  const hull = convexHull(pts);
  // Inflate the hull slightly so the boundary doesn't pass directly through markers.
  const centroid = [
    hull.reduce((a, p) => a + p[0], 0) / hull.length,
    hull.reduce((a, p) => a + p[1], 0) / hull.length,
  ];
  const inflated = hull.map(([lat, lng]) => [
    lat + (lat - centroid[0]) * 0.18,
    lng + (lng - centroid[1]) * 0.18,
  ]);

  state.boundaryLayer = L.polygon(inflated, {
    color: '#6e1527',
    weight: 2,
    opacity: 0.7,
    fillColor: '#6e1527',
    fillOpacity: 0.06,
    interactive: false,
    dashArray: '6 4',
  }).addTo(state.map);
}

// ── Andrew's monotone chain convex hull. Each pt is [lat, lng].
function convexHull(points) {
  const pts = points.slice().sort((a, b) =>
    a[0] === b[0] ? a[1] - b[1] : a[0] - b[0]
  );
  if (pts.length <= 1) return pts;
  const cross = (o, a, b) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  }
  const upper = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }
  lower.pop(); upper.pop();
  return lower.concat(upper);
}

// =====================================================
//   HEADER STATS + LEGEND
// =====================================================

function renderHeaderStats() {
  const positionCount = state.programs.reduce((s, p) => s + (p.position_count || 0), 0);
  const hiringCount   = state.refreshStatus ? state.refreshStatus.positions_hiring : 0;
  el.headerStats.innerHTML = `
    <div class="p2p-stat">
      <div class="p2p-stat-n">${state.schools.length}</div>
      <div class="p2p-stat-l">SBCUSD<br>schools</div>
    </div>
    <div class="p2p-stat">
      <div class="p2p-stat-n">${state.programs.length}</div>
      <div class="p2p-stat-l">CTE<br>programs</div>
    </div>
    <div class="p2p-stat">
      <div class="p2p-stat-n">${positionCount}</div>
      <div class="p2p-stat-l">County<br>positions</div>
    </div>
    <div class="p2p-stat ${hiringCount ? 'p2p-stat--hiring' : ''}">
      <div class="p2p-stat-n">${hiringCount}</div>
      <div class="p2p-stat-l">Hiring<br>now</div>
    </div>
  `;
}

function renderLegend() {
  el.legendGrid.innerHTML = state.programs
    .slice()
    .sort((a, b) => a.display_order - b.display_order)
    .map(p => `
      <div class="p2p-legend-item" data-pid="${p.id}" title="${escapeHtml(p.name)}">
        <span class="p2p-legend-swatch" style="background:${programColor(p.id)}"></span>
        <span class="p2p-legend-label">${escapeHtml(PROGRAM_SHORT[p.name] || p.name)}</span>
      </div>
    `)
    .join('');
  // Clicking a legend swatch filters the map to that program (matches chip click).
  el.legendGrid.querySelectorAll('.p2p-legend-item').forEach(item => {
    item.addEventListener('click', () => {
      const pid  = parseInt(item.dataset.pid);
      const prog = state.programs.find(p => p.id === pid);
      if (prog) onProgramChipClick(prog);
    });
  });
}

function renderFooterRefresh() {
  if (state.refreshStatus && state.refreshStatus.last_refresh) {
    el.footerRefresh.textContent = ` · overlay refreshed ${state.refreshStatus.last_refresh} UTC`;
  } else {
    el.footerRefresh.textContent = '';
  }
}

// =====================================================
//   PROGRAM CHIPS
// =====================================================

function renderProgramChips() {
  const labelSpan = el.chipBar.querySelector('.p2p-chip-label');
  el.chipBar.innerHTML = '';
  if (labelSpan) el.chipBar.appendChild(labelSpan);

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
        <span class="p2p-chip-dot" style="background:${programColor(prog.id)}"></span>
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
  state.selectedProgramId = (state.selectedProgramId === prog.id) ? null : prog.id;
  refreshChipActiveStates();

  if (state.selectedProgramId) {
    const matches = state.schools.filter(s => s.program_ids.includes(state.selectedProgramId));
    if (matches.length) {
      selectSchool(matches[0], { preferredProgramId: state.selectedProgramId });
      const pts = matches.filter(s => s.latitude).map(s => [s.latitude, s.longitude]);
      if (pts.length) state.map.fitBounds(pts, { padding: [60, 60], maxZoom: 14 });
    }
  }
  renderMarkers();
  renderHeatmap();
}

function refreshChipActiveStates() {
  el.chipBar.querySelectorAll('.p2p-chip').forEach(c => {
    if (c.classList.contains('p2p-chip--reset')) return;
    c.classList.toggle('p2p-chip--active', parseInt(c.dataset.pid) === state.selectedProgramId);
  });
}

// =====================================================
//   SCHOOL SELECTION → LEFT DRAWER
// =====================================================

function selectSchool(school, { preferredProgramId = null } = {}) {
  state.selectedSchool = school;
  el.leftEmpty.hidden  = true;
  el.leftSchool.hidden = false;

  el.leftSchoolName.textContent = school.name;
  el.leftSchoolDist.textContent = school.district;

  const primary = schoolPrimaryProgramId(school);
  if (primary) {
    const prog = state.programs.find(p => p.id === primary);
    el.leftSchoolPrimary.innerHTML = `
      <span class="p2p-primary-swatch" style="background:${programColor(primary)}"></span>
      Primary: ${escapeHtml(prog?.name || '')}
    `;
  } else {
    el.leftSchoolPrimary.innerHTML = '';
  }

  const offered = school.pathway_ids
    .map(pid => state.pathways.find(p => p.id === pid))
    .filter(Boolean);
  const bySector = {};
  offered.forEach(p => {
    const sec = p.sector || 'Other';
    (bySector[sec] = bySector[sec] || []).push(p);
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
        const isHiring = pw.cte_program_id && state.hiringProgramIds.has(pw.cte_program_id);
        const progColor = pw.cte_program_id ? programColor(pw.cte_program_id) : null;
        btn.innerHTML = `
          ${progColor ? `<span class="p2p-pathway-dot" style="background:${progColor}"></span>` : ''}
          <span class="p2p-pathway-name">${escapeHtml(pw.name)}</span>
          ${isHiring ? '<span class="p2p-pathway-hiring" title="Has a position hiring now">●</span>' : ''}
          ${pw.cte_program_id === null
            ? '<span class="p2p-pathway-untied" title="No county program tied">○</span>'
            : ''}
        `;
        btn.addEventListener('click', () => onPathwayClick(pw));
        group.appendChild(btn);
      });
      el.leftPathways.appendChild(group);
    });
  }

  // Mark in-program pathways and auto-pick one when a chip drove the selection.
  if (preferredProgramId) {
    el.leftPathways.querySelectorAll('.p2p-pathway').forEach(b => {
      const pid = parseInt(b.dataset.pid);
      const pw  = state.pathways.find(x => x.id === pid);
      if (pw && pw.cte_program_id === preferredProgramId) {
        b.classList.add('p2p-pathway--in-program');
      }
    });
    const candidate = offered.find(p => p.cte_program_id === preferredProgramId);
    if (candidate) onPathwayClick(candidate);
    else            clearRightPanel();
  } else {
    clearRightPanel();
  }

  openDrawer('left');
  renderMarkers();
  if (!preferredProgramId && school.latitude && school.longitude) {
    state.map.setView([school.latitude, school.longitude], Math.max(state.map.getZoom(), 14));
  }
}

// =====================================================
//   PATHWAY CLICK → RIGHT DRAWER
// =====================================================

async function onPathwayClick(pathway) {
  state.selectedPathwayId = pathway.id;
  document.querySelectorAll('.p2p-pathway').forEach(b => {
    b.classList.toggle('p2p-pathway--active', parseInt(b.dataset.pid) === pathway.id);
  });

  el.rightEmpty.hidden = true;
  el.rightPositions.innerHTML = '<div class="p2p-loading">Loading positions…</div>';
  el.statSchool.textContent  = state.selectedSchool ? state.selectedSchool.name : '—';
  el.statProgram.textContent = '…';
  el.statCount.textContent   = '…';
  el.statPay.textContent     = '…';
  openDrawer('right');

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
  el.rightEmpty.hidden = false;
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

    const liveUrl   = pos.is_hiring_now && pos.current_postings[0]?.url;
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

    const mqPreview = pos.mqs_text
      ? pos.mqs_text.split(/\r?\n/).map(s => s.trim()).find(s => s.length > 0) || ''
      : '';
    const mqsHtml = pos.mqs_text
      ? `<div class="p2p-pos-mq-preview">${escapeHtml(mqPreview)}</div>
         <details class="p2p-pos-mqs">
           <summary>Full minimum qualifications</summary>
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
      <div class="p2p-pos-foot">${applyBtn}</div>
    `;
    el.rightPositions.appendChild(card);
  });
}

// =====================================================
//   EVENT BINDING + RESET
// =====================================================

function bindEvents() {
  el.leftDrawerTab.addEventListener('click',  () => toggleDrawer('left'));
  el.rightDrawerTab.addEventListener('click', () => toggleDrawer('right'));

  el.toggleBoundary.addEventListener('change', drawBoundary);
  el.toggleHeatmap.addEventListener('change',  renderHeatmap);
  el.toggleCluster.addEventListener('change', onClusterToggle);
}

function onClusterToggle() {
  const useCluster = el.toggleCluster.checked;
  if (useCluster) {
    if (state.map.hasLayer(state.markerLayer)) state.map.removeLayer(state.markerLayer);
    if (!state.map.hasLayer(state.cluster))    state.map.addLayer(state.cluster);
  } else {
    if (state.map.hasLayer(state.cluster))     state.map.removeLayer(state.cluster);
    if (!state.map.hasLayer(state.markerLayer)) state.map.addLayer(state.markerLayer);
  }
  renderMarkers();
}

function resetAll() {
  state.selectedProgramId = null;
  state.selectedSchool    = null;
  state.selectedPathwayId = null;
  refreshChipActiveStates();
  el.leftSchool.hidden = true;
  el.leftEmpty.hidden  = false;
  el.leftPathways.innerHTML = '';
  el.leftSchoolPrimary.innerHTML = '';
  clearRightPanel();
  closeDrawer('left');
  closeDrawer('right');
  renderMarkers();
  renderHeatmap();
  fitMapToSchools();
}

// =====================================================
//   DATA LOADING
// =====================================================

async function loadSchoolsFull() {
  try { state.schools = await apiFetch('/api/schools/full'); }
  catch (e) { console.error(e); state.schools = []; }
}
async function loadPrograms() {
  try { state.programs = await apiFetch('/api/programs'); }
  catch (e) { console.error(e); state.programs = []; }
}
async function loadPathways() {
  try { state.pathways = await apiFetch('/api/pathways'); }
  catch (e) { console.error(e); state.pathways = []; }
}
async function loadRefreshStatus() {
  try {
    state.refreshStatus = await apiFetch('/api/refresh-status');
    state.hiringProgramIds = new Set(
      (state.refreshStatus.per_program || []).filter(r => r.posting_count > 0).map(r => r.id)
    );
  } catch (e) { console.warn(e); state.refreshStatus = null; }
}
