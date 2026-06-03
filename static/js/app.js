/* =====================================================
   CTE JOB DASHBOARD — app.js
   Interactive GIS map of San Bernardino County high schools,
   filterable by CTE pathway, county program, and district.

   The map is the primary interface. Picking a school surfaces its
   pathways; picking a pathway surfaces the county entry-level
   positions tied to that pathway's CTE program (with MQs, pay,
   career ladder, and the live "Hiring now" overlay).
   ===================================================== */

'use strict';

// ── Global state ──────────────────────────────────────
const state = {
  schools:         [],   // [{id, name, district, lat, lng, pathway_ids, program_ids, pathway_count}]
  programs:        [],   // [{id, name, position_count, display_order}]
  pathways:        [],   // [{id, name, sector}]
  careers:         [],
  filter:          { programId: null, pathwayId: null, district: null },
  selectedSchool:  null,
  selectedPathway: null,
  map:             null,
  cluster:         null, // L.markerClusterGroup
  markers:         [],   // [{schoolId, marker, baseIcon, matchIcon, dimIcon, selectedIcon}]
};

// ── DOM refs ──────────────────────────────────────────
const el = {
  filterProgram:          document.getElementById('filter-program'),
  filterPathway:          document.getElementById('filter-pathway'),
  filterDistrict:         document.getElementById('filter-district'),
  clearFiltersBtn:        document.getElementById('clear-filters-btn'),
  filterCount:            document.getElementById('filter-count'),

  schoolDetail:           document.getElementById('school-detail'),
  schoolDetailName:       document.getElementById('school-detail-name'),
  schoolDetailDistrict:   document.getElementById('school-detail-district'),
  schoolPathwayChips:     document.getElementById('school-pathway-chips'),
  clearSchoolBtn:         document.getElementById('clear-school-btn'),

  schoolSelect:           document.getElementById('school-select'),
  pathwaySelect:          document.getElementById('pathway-select'),
  careerSelect:           document.getElementById('career-select'),
  pathwayRecommendations: document.getElementById('pathway-recommendations'),
  pathwayCards:           document.getElementById('pathway-cards'),

  loading:                document.getElementById('loading'),
  resultsSection:         document.getElementById('results-section'),
  resultsHeading:         document.getElementById('results-heading'),
  resultsCount:           document.getElementById('results-count'),
  resultsList:            document.getElementById('results-list'),
  noResults:              document.getElementById('no-results'),
  apiUnavailable:         document.getElementById('api-unavailable'),
  pathwayInfoBar:         document.getElementById('pathway-info-bar'),
  pathwayInfoName:        document.getElementById('pathway-info-name'),
  pathwayInfoSector:      document.getElementById('pathway-info-sector'),
  clearResultsBtn:        document.getElementById('clear-results-btn'),
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
  bindEvents();
  await Promise.all([
    loadSchoolsFull(),
    loadPrograms(),
    loadPathways(),
    loadCareers(),
  ]);
  buildFilterOptions();
  populateAltFlowDropdowns();
  renderMarkers();
});

// =====================================================
//   MAP — Leaflet + OpenStreetMap + MarkerCluster
// =====================================================

function initMap() {
  state.map = L.map('map', { zoomControl: true }).setView([34.30, -116.95], 9);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 18,
  }).addTo(state.map);

  state.cluster = L.markerClusterGroup({
    showCoverageOnHover: false,
    spiderfyOnMaxZoom: true,
    maxClusterRadius: 40,
  });
  state.map.addLayer(state.cluster);
}

// Three marker icon flavours: default (filter inactive), match (filter active + school
// matches), dim (filter active + school doesn't match), selected (clicked school).
function makeIcon({ size, color, border = '#fff', shadow = '0 1px 4px rgba(0,0,0,0.3)' }) {
  return L.divIcon({
    className: '',
    html: `<div style="
      width:${size}px;height:${size}px;
      background:${color};border:2px solid ${border};
      border-radius:50%;box-shadow:${shadow};
    "></div>`,
    iconSize:   [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

const ICONS = {
  default:  () => makeIcon({ size: 14, color: '#1a4f8a' }),
  match:    () => makeIcon({ size: 16, color: '#1a4f8a' }),
  selected: () => makeIcon({ size: 20, color: '#e07b1a', shadow: '0 2px 8px rgba(0,0,0,0.45)' }),
  dim:      () => makeIcon({ size: 10, color: '#cfd5dc', border: 'rgba(255,255,255,0.7)', shadow: 'none' }),
};

function renderMarkers() {
  // Wipe and rebuild the marker layer so colors track the current filter state.
  state.cluster.clearLayers();
  state.markers = [];

  const filterActive = hasActiveFilter();
  let matchCount = 0;

  state.schools.forEach(school => {
    if (!school.latitude || !school.longitude) return;

    const isMatch    = filterActive && schoolMatches(school);
    const isSelected = state.selectedSchool && state.selectedSchool.id === school.id;

    let icon;
    if (isSelected)            icon = ICONS.selected();
    else if (!filterActive)    icon = ICONS.default();
    else if (isMatch)          icon = ICONS.match();
    else                       icon = ICONS.dim();

    const marker = L.marker([school.latitude, school.longitude], {
      icon,
      title:    school.name,
      opacity:  (filterActive && !isMatch && !isSelected) ? 0.55 : 1,
      keyboard: !filterActive || isMatch || isSelected,
    });

    const programNames = school.program_ids
      .map(pid => (state.programs.find(p => p.id === pid) || {}).name)
      .filter(Boolean);
    marker.bindPopup(`
      <div style="font-family:system-ui,sans-serif;min-width:180px;">
        <strong style="color:#0f2f54;">${escapeHtml(school.name)}</strong><br>
        <span style="font-size:12px;color:#666;">${escapeHtml(school.district)}</span><br>
        <span style="font-size:12px;color:#1a4f8a;">
          ${school.pathway_count} pathway${school.pathway_count !== 1 ? 's' : ''}
          ${programNames.length ? ' across ' + programNames.length + ' county program' + (programNames.length === 1 ? '' : 's') : ''}
        </span>
      </div>
    `);
    marker.on('click', () => selectSchoolById(school.id));

    state.cluster.addLayer(marker);
    state.markers.push({ schoolId: school.id, marker });

    if (!filterActive || isMatch) matchCount++;
  });

  updateFilterCount(matchCount, filterActive);
}

// =====================================================
//   FILTERS
// =====================================================

function hasActiveFilter() {
  const f = state.filter;
  return !!(f.programId || f.pathwayId || f.district);
}

function schoolMatches(school) {
  const f = state.filter;
  if (f.programId && !school.program_ids.includes(f.programId)) return false;
  if (f.pathwayId && !school.pathway_ids.includes(f.pathwayId)) return false;
  if (f.district && school.district !== f.district) return false;
  return true;
}

function updateFilterCount(matchCount, filterActive) {
  const total = state.schools.length;
  el.filterCount.textContent = filterActive
    ? `${matchCount} of ${total} schools match`
    : `${total} schools`;
  el.filterCount.classList.toggle('filter-status--active', filterActive);
}

function buildFilterOptions() {
  // Program <select>
  el.filterProgram.innerHTML = '<option value="">All 10 programs</option>';
  state.programs
    .slice()
    .sort((a, b) => a.display_order - b.display_order)
    .forEach(p => {
      const opt = document.createElement('option');
      opt.value       = p.id;
      opt.textContent = `${p.name}`;
      el.filterProgram.appendChild(opt);
    });

  // Pathway <select> (will be re-populated when program filter changes)
  populatePathwayFilter(state.pathways);

  // District <select>
  el.filterDistrict.innerHTML = '<option value="">All districts</option>';
  Array.from(new Set(state.schools.map(s => s.district))).sort().forEach(d => {
    const opt = document.createElement('option');
    opt.value       = d;
    opt.textContent = d;
    el.filterDistrict.appendChild(opt);
  });
}

function populatePathwayFilter(pathways) {
  el.filterPathway.innerHTML = '<option value="">All pathways</option>';
  const bySector = {};
  pathways.forEach(p => {
    const sector = p.sector || 'Other';
    if (!bySector[sector]) bySector[sector] = [];
    bySector[sector].push(p);
  });
  Object.keys(bySector).sort().forEach(sector => {
    const group = document.createElement('optgroup');
    group.label = sector;
    bySector[sector].forEach(p => {
      const opt = document.createElement('option');
      opt.value       = p.id;
      opt.textContent = p.name;
      group.appendChild(opt);
    });
    el.filterPathway.appendChild(group);
  });
}

function onProgramFilterChange() {
  const id = parseInt(el.filterProgram.value) || null;
  state.filter.programId = id;

  // Narrow the Pathway dropdown to pathways whose schools are in this program.
  if (id) {
    const matchingPathwayIds = new Set();
    state.schools.forEach(s => {
      if (s.program_ids.includes(id)) {
        s.pathway_ids.forEach(pid => matchingPathwayIds.add(pid));
      }
    });
    populatePathwayFilter(state.pathways.filter(p => matchingPathwayIds.has(p.id)));
  } else {
    populatePathwayFilter(state.pathways);
  }
  // Reset pathway filter if the current pathway is no longer reachable.
  if (state.filter.pathwayId &&
      ![...el.filterPathway.options].some(o => parseInt(o.value) === state.filter.pathwayId)) {
    state.filter.pathwayId = null;
    el.filterPathway.value = '';
  } else if (state.filter.pathwayId) {
    el.filterPathway.value = String(state.filter.pathwayId);
  }
  renderMarkers();
}

function onPathwayFilterChange() {
  state.filter.pathwayId = parseInt(el.filterPathway.value) || null;
  renderMarkers();
}

function onDistrictFilterChange() {
  state.filter.district = el.filterDistrict.value || null;
  renderMarkers();
}

function clearFilters() {
  state.filter = { programId: null, pathwayId: null, district: null };
  el.filterProgram.value  = '';
  el.filterPathway.value  = '';
  el.filterDistrict.value = '';
  populatePathwayFilter(state.pathways);
  renderMarkers();
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

async function loadCareers() {
  try {
    state.careers = await apiFetch('/api/careers');
    populateCareerDropdown();
  } catch (e) {
    console.error('Failed to load careers:', e);
  }
}

function populateAltFlowDropdowns() {
  // Alt-flow school dropdown (collapsed section). Built from state.schools already in memory.
  const byDistrict = {};
  state.schools.forEach(s => {
    if (!byDistrict[s.district]) byDistrict[s.district] = [];
    byDistrict[s.district].push(s);
  });
  el.schoolSelect.innerHTML = '<option value="">-- Choose a school --</option>';
  Object.keys(byDistrict).sort().forEach(district => {
    const group = document.createElement('optgroup');
    group.label = district;
    byDistrict[district].forEach(school => {
      const opt = document.createElement('option');
      opt.value       = school.id;
      opt.textContent = school.name;
      group.appendChild(opt);
    });
    el.schoolSelect.appendChild(group);
  });
}

function populateCareerDropdown() {
  el.careerSelect.innerHTML = '<option value="">-- Choose a career --</option>';
  state.careers.forEach(career => {
    const opt = document.createElement('option');
    opt.value       = career.id;
    opt.textContent = career.name;
    el.careerSelect.appendChild(opt);
  });
}

// =====================================================
//   EVENT BINDING
// =====================================================

function bindEvents() {
  el.filterProgram.addEventListener('change', onProgramFilterChange);
  el.filterPathway.addEventListener('change', onPathwayFilterChange);
  el.filterDistrict.addEventListener('change', onDistrictFilterChange);
  el.clearFiltersBtn.addEventListener('click', clearFilters);
  el.clearSchoolBtn.addEventListener('click', clearSchoolDetail);

  el.schoolSelect.addEventListener('change', onAltSchoolChange);
  el.pathwaySelect.addEventListener('change', onAltPathwayChange);
  el.careerSelect.addEventListener('change', onCareerChange);
  el.clearResultsBtn.addEventListener('click', clearResults);
}

// =====================================================
//   SCHOOL SELECTION (from map click OR alt-flow dropdown)
// =====================================================

function selectSchoolById(schoolId) {
  const school = state.schools.find(s => s.id === schoolId);
  if (!school) return;
  state.selectedSchool = school;
  renderMarkers();           // refresh icons so the selected one becomes orange
  renderSchoolDetail(school);
  if (school.latitude && state.map) {
    state.map.setView([school.latitude, school.longitude], 13);
  }
}

function clearSchoolDetail() {
  state.selectedSchool = null;
  hide(el.schoolDetail);
  el.schoolPathwayChips.innerHTML = '';
  clearResults();
  renderMarkers();
}

function renderSchoolDetail(school) {
  el.schoolDetailName.textContent     = school.name;
  el.schoolDetailDistrict.textContent = school.district;

  // Build pathway chips from the in-memory pathway catalogue.
  el.schoolPathwayChips.innerHTML = '';
  const pathwayObjects = school.pathway_ids
    .map(pid => state.pathways.find(p => p.id === pid))
    .filter(Boolean)
    .sort((a, b) => (a.sector || '').localeCompare(b.sector || '') || a.name.localeCompare(b.name));

  if (pathwayObjects.length === 0) {
    el.schoolPathwayChips.innerHTML =
      '<p style="font-size:0.85rem;color:#666;">No pathway data on file.</p>';
  } else {
    pathwayObjects.forEach(p => {
      const chip = document.createElement('button');
      chip.type      = 'button';
      chip.className = 'pathway-chip';
      chip.innerHTML = `
        <span class="pathway-chip-name">${escapeHtml(p.name)}</span>
        ${p.sector ? `<span class="pathway-chip-sector">${escapeHtml(p.sector)}</span>` : ''}
      `;
      chip.addEventListener('click', () => {
        document.querySelectorAll('.pathway-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        fetchAndRenderPositions(p.id, p.name, p.sector || '');
      });
      el.schoolPathwayChips.appendChild(chip);
    });
  }
  show(el.schoolDetail);
}

// =====================================================
//   ALT FLOW 1 — School dropdown → pathway dropdown → positions
// =====================================================

async function onAltSchoolChange() {
  const schoolId = parseInt(el.schoolSelect.value);
  el.pathwaySelect.innerHTML = '<option value="">-- Choose a pathway --</option>';
  el.pathwaySelect.disabled  = true;
  if (!schoolId) return;

  selectSchoolById(schoolId);

  try {
    const data     = await apiFetch(`/api/schools/${schoolId}/pathways`);
    const pathways = data.pathways;
    if (!pathways.length) {
      el.pathwaySelect.innerHTML = '<option value="">No pathways found</option>';
      return;
    }
    const bySector = {};
    pathways.forEach(p => {
      const s = p.sector || 'Other';
      if (!bySector[s]) bySector[s] = [];
      bySector[s].push(p);
    });
    Object.keys(bySector).sort().forEach(sector => {
      const group = document.createElement('optgroup');
      group.label = sector;
      bySector[sector].forEach(pathway => {
        const opt = document.createElement('option');
        opt.value       = pathway.id;
        opt.textContent = pathway.name;
        group.appendChild(opt);
      });
      el.pathwaySelect.appendChild(group);
    });
    el.pathwaySelect.disabled = false;
  } catch (e) {
    console.error('Failed to load pathways for school:', e);
    el.pathwaySelect.innerHTML = '<option value="">Error loading pathways</option>';
  }
}

async function onAltPathwayChange() {
  const pathwayId = parseInt(el.pathwaySelect.value);
  if (!pathwayId) return;
  const selectedOpt = el.pathwaySelect.options[el.pathwaySelect.selectedIndex];
  const name        = selectedOpt.text;
  const sector      = selectedOpt.closest('optgroup')?.label || '';
  await fetchAndRenderPositions(pathwayId, name, sector);
}

// =====================================================
//   ALT FLOW 2 — Career → recommended pathways → positions
// =====================================================

async function onCareerChange() {
  const careerId = parseInt(el.careerSelect.value);
  hide(el.pathwayRecommendations);
  el.pathwayCards.innerHTML = '';
  clearResults();
  if (!careerId) return;

  try {
    const data     = await apiFetch(`/api/pathways/by-career/${careerId}`);
    const pathways = data.pathways;
    if (!pathways.length) {
      el.pathwayCards.innerHTML =
        '<p style="font-size:0.85rem;color:#666;">No pathways found for this career.</p>';
      show(el.pathwayRecommendations);
      return;
    }
    pathways.forEach(pathway => {
      const card       = document.createElement('div');
      card.className   = 'pathway-rec-card';
      card.dataset.id  = pathway.id;
      const schoolList  = pathway.schools.slice(0, 3).map(s => s.name).join(', ');
      const moreSchools = pathway.schools.length > 3 ? ` +${pathway.schools.length - 3} more` : '';
      card.innerHTML = `
        <div class="pathway-rec-name">${escapeHtml(pathway.name)}</div>
        <div class="pathway-rec-sector">${escapeHtml(pathway.sector || '')}</div>
        ${pathway.schools.length > 0
          ? `<div class="pathway-rec-schools">📍 ${escapeHtml(schoolList)}${moreSchools}</div>`
          : ''}
      `;
      card.addEventListener('click', () => {
        document.querySelectorAll('.pathway-rec-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        fetchAndRenderPositions(pathway.id, pathway.name, pathway.sector || '');
        if (pathway.schools.length > 0 && state.map) {
          const first = pathway.schools[0];
          if (first.latitude) state.map.setView([first.latitude, first.longitude], 11);
        }
      });
      el.pathwayCards.appendChild(card);
    });
    show(el.pathwayRecommendations);
  } catch (e) {
    console.error('Failed to load pathways for career:', e);
    el.pathwayCards.innerHTML =
      '<p style="font-size:0.85rem;color:#c0392b;">Error loading recommendations.</p>';
    show(el.pathwayRecommendations);
  }
}

// =====================================================
//   COUNTY POSITION FETCH + RENDER
// =====================================================

async function fetchAndRenderPositions(pathwayId, pathwayName, sector) {
  clearResultsDisplay();
  show(el.loading);
  show(el.resultsSection);

  el.pathwayInfoName.textContent   = pathwayName;
  el.pathwayInfoSector.textContent = sector ? `· ${sector}` : '';
  show(el.pathwayInfoBar);

  el.resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    const data = await apiFetch(`/api/jobs?pathway_id=${pathwayId}`);
    hide(el.loading);

    if (!data.program) {
      show(el.noResults);
      el.resultsCount.textContent = '0 positions';
      const note = document.createElement('div');
      note.className = 'state-box';
      note.innerHTML = `
        <span class="state-icon">🏛</span>
        <h3>No county positions tied to this pathway yet</h3>
        <p>${escapeHtml(data.message || 'This pathway is not currently mapped to one of the county\'s 10 CTE programs.')}</p>
        <p><strong>Speak with your counselor</strong> for guidance.</p>
      `;
      el.resultsList.appendChild(note);
      return;
    }
    if (!data.positions || data.positions.length === 0) {
      show(el.noResults);
      el.resultsCount.textContent = '0 positions';
      return;
    }
    el.resultsCount.textContent   = `${data.total} entry position${data.total !== 1 ? 's' : ''}`;
    el.resultsHeading.textContent = `${data.program.name} careers`;
    renderProgramBanner(data.program);
    renderPositionCards(data.positions);
  } catch (e) {
    hide(el.loading);
    show(el.apiUnavailable);
    el.resultsCount.textContent = '';
    console.error('Failed to fetch positions:', e);
  }
}

function renderProgramBanner(program) {
  const banner = document.createElement('div');
  banner.className = 'program-banner';
  banner.innerHTML = `
    <div class="program-banner-title">San Bernardino County · ${escapeHtml(program.name)}</div>
    ${program.description
      ? `<div class="program-banner-desc">${escapeHtml(program.description)}</div>`
      : ''}
  `;
  el.resultsList.appendChild(banner);
}

function renderPositionCards(positions) {
  positions.forEach(pos => {
    const card = document.createElement('div');
    card.className = 'position-card';
    if (pos.job_code === 'NEW') card.classList.add('position-card--new');
    if (pos.is_hiring_now)      card.classList.add('position-card--hiring');

    const codeBadge = pos.job_code
      ? `<span class="position-code">${escapeHtml(pos.job_code)}</span>`
      : '';

    const hiringPill = pos.is_hiring_now
      ? `<span class="position-hiring-pill" title="Currently posted on governmentjobs.com">
           ● Hiring now${pos.current_postings.length > 1 ? ` · ${pos.current_postings.length}` : ''}
         </span>`
      : '';

    const salary = pos.salary
      ? `<span class="position-meta-item salary">💰 ${escapeHtml(pos.salary)}</span>`
      : '';

    const grade = pos.grade
      ? `<span class="position-meta-item">Grade ${escapeHtml(pos.grade)}</span>`
      : '';

    const union = pos.union_code
      ? `<span class="position-meta-item">Union ${escapeHtml(pos.union_code)}</span>`
      : '';

    const mqs = pos.mqs_text
      ? `<details class="position-mqs">
          <summary>Minimum qualifications</summary>
          <pre>${escapeHtml(pos.mqs_text)}</pre>
        </details>`
      : '';

    const ladder = pos.ladder && pos.ladder.length > 1
      ? renderLadder(pos.ladder)
      : '';

    const livePostings = pos.is_hiring_now ? renderLivePostings(pos.current_postings) : '';

    const liveUrl   = pos.is_hiring_now && pos.current_postings[0]?.url;
    const applyHref = liveUrl || pos.apply_url;
    const applyLabel = pos.is_hiring_now
      ? 'Apply now ↗'
      : (pos.apply_url ? 'See current postings ↗' : 'Not yet posting');

    const applyBtn = applyHref
      ? `<a class="position-apply-btn ${pos.is_hiring_now ? 'position-apply-btn--hiring' : ''}"
            href="${escapeHtml(applyHref)}"
            target="_blank"
            rel="noopener noreferrer">
            ${applyLabel}
         </a>`
      : `<span class="position-apply-btn" style="opacity:0.4;cursor:default;">${applyLabel}</span>`;

    card.innerHTML = `
      <div class="position-header">
        <div>
          <div class="position-title">${escapeHtml(pos.title)} ${codeBadge} ${hiringPill}</div>
          <div class="position-meta">${salary} ${grade} ${union}</div>
        </div>
        ${applyBtn}
      </div>
      ${livePostings}
      ${ladder}
      ${mqs}
      ${pos.notes ? `<div class="position-notes">⚙ ${escapeHtml(pos.notes)}</div>` : ''}
    `;
    el.resultsList.appendChild(card);
  });
}

function renderLivePostings(postings) {
  if (postings.length <= 1) return '';
  const items = postings.map(p => `
    <li>
      <a href="${escapeHtml(p.url)}" target="_blank" rel="noopener noreferrer">
        ${escapeHtml(p.title)}
      </a>
      ${p.closes ? `<span class="live-posting-closes">closes ${escapeHtml(p.closes)}</span>` : ''}
    </li>
  `).join('');
  return `
    <div class="position-live-postings">
      <div class="position-live-postings-label">${postings.length} current postings</div>
      <ul>${items}</ul>
    </div>
  `;
}

function renderLadder(ladder) {
  const steps = ladder.map(step => {
    const cls  = step.is_entry ? 'ladder-step ladder-step--entry' : 'ladder-step';
    const code = step.job_code && step.job_code !== 'NEW'
      ? `<span class="ladder-code">${escapeHtml(step.job_code)}</span>`
      : '';
    return `<div class="${cls}">
      <span class="ladder-step-num">${step.step}</span>
      <span class="ladder-step-title">${escapeHtml(step.title)}</span>
      ${code}
    </div>`;
  }).join('<span class="ladder-arrow">→</span>');
  return `
    <div class="position-ladder">
      <div class="position-ladder-label">Career progression</div>
      <div class="ladder-chain">${steps}</div>
    </div>
  `;
}

// =====================================================
//   CLEAR / RESET
// =====================================================

function clearResultsDisplay() {
  el.resultsList.innerHTML    = '';
  el.resultsCount.textContent = '';
  hide(el.noResults);
  hide(el.apiUnavailable);
  hide(el.loading);
}

function clearResults() {
  clearResultsDisplay();
  hide(el.resultsSection);
  hide(el.pathwayInfoBar);
  el.resultsHeading.textContent = 'County career opportunities';
  state.selectedPathway         = null;
}
