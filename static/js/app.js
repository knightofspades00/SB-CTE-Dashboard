/* =====================================================
   CTE JOB DASHBOARD — app.js
   GIS map of County of San Bernardino entry-level positions
   tied to CTE programs, fed by a curated catalog (not a live API).
   ===================================================== */

'use strict';

// ── Global state ──────────────────────────────────────
const state = {
  schools:         [],
  careers:         [],
  selectedSchool:  null,
  selectedPathway: null,
  activeFlow:      null,
  map:             null,
  markers:         [],
};

// ── DOM refs ──────────────────────────────────────────
const el = {
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
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  loadSchools();
  loadCareers();
  bindEvents();
});

// =====================================================
//   MAP — Leaflet + OpenStreetMap
// =====================================================

function initMap() {
  state.map = L.map('map').setView([34.1083, -117.2898], 10);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 18,
  }).addTo(state.map);
}

function placeMarkers() {
  state.markers.forEach(({ marker }) => marker.remove());
  state.markers = [];

  const defaultIcon = L.divIcon({
    className: '',
    html: `<div style="
      width:14px;height:14px;
      background:#1a4f8a;
      border:2px solid #fff;
      border-radius:50%;
      box-shadow:0 1px 4px rgba(0,0,0,0.3);
    "></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });

  const activeIcon = L.divIcon({
    className: '',
    html: `<div style="
      width:18px;height:18px;
      background:#e07b1a;
      border:2px solid #fff;
      border-radius:50%;
      box-shadow:0 1px 6px rgba(0,0,0,0.4);
    "></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

  state.schools.forEach(school => {
    if (!school.latitude || !school.longitude) return;

    const marker = L.marker([school.latitude, school.longitude], {
      icon:  defaultIcon,
      title: school.name,
    }).addTo(state.map);

    marker.bindPopup(`
      <div style="font-family:system-ui,sans-serif;min-width:160px;">
        <strong style="color:#0f2f54;">${escapeHtml(school.name)}</strong><br>
        <span style="font-size:12px;color:#666;">${escapeHtml(school.district)}</span><br>
        <span style="font-size:12px;color:#1a4f8a;">
          ${school.pathway_count} pathway${school.pathway_count !== 1 ? 's' : ''}
        </span>
      </div>
    `);

    marker.on('click', () => {
      selectSchoolById(school.id);
    });

    state.markers.push({
      schoolId:    school.id,
      marker,
      defaultIcon,
      activeIcon,
    });
  });
}

function highlightMarker(schoolId) {
  state.markers.forEach(({ schoolId: sid, marker, defaultIcon, activeIcon }) => {
    marker.setIcon(sid === schoolId ? activeIcon : defaultIcon);
  });
}

// =====================================================
//   DATA LOADING
// =====================================================

async function loadSchools() {
  try {
    state.schools = await apiFetch('/api/schools');
    populateSchoolDropdown();
    placeMarkers();
  } catch (e) {
    console.error('Failed to load schools:', e);
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

function populateSchoolDropdown() {
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
  el.schoolSelect.addEventListener('change', onSchoolChange);
  el.pathwaySelect.addEventListener('change', onPathwayChange);
  el.careerSelect.addEventListener('change', onCareerChange);
  el.clearResultsBtn.addEventListener('click', clearResults);
}

// =====================================================
//   FLOW 1 — School → Pathway → County Positions
// =====================================================

async function onSchoolChange() {
  const schoolId = parseInt(el.schoolSelect.value);

  el.pathwaySelect.innerHTML = '<option value="">-- Choose a pathway --</option>';
  el.pathwaySelect.disabled  = true;
  clearResults();

  if (!schoolId) return;

  highlightMarker(schoolId);

  const school = state.schools.find(s => s.id === schoolId);
  if (school && school.latitude && state.map) {
    state.map.setView([school.latitude, school.longitude], 13);
  }

  try {
    const data     = await apiFetch(`/api/schools/${schoolId}/pathways`);
    const pathways = data.pathways;

    if (pathways.length === 0) {
      el.pathwaySelect.innerHTML = '<option value="">No pathways found</option>';
      return;
    }

    const bySector = {};
    pathways.forEach(p => {
      const sector = p.sector || 'Other';
      if (!bySector[sector]) bySector[sector] = [];
      bySector[sector].push(p);
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
    state.activeFlow = 'flow1';

  } catch (e) {
    console.error('Failed to load pathways for school:', e);
    el.pathwaySelect.innerHTML = '<option value="">Error loading pathways</option>';
  }
}

function selectSchoolById(schoolId) {
  el.schoolSelect.value = schoolId;
  el.schoolSelect.dispatchEvent(new Event('change'));
  document.getElementById('controls-section')
    .scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function onPathwayChange() {
  const pathwayId = parseInt(el.pathwaySelect.value);
  if (!pathwayId) return;

  const selectedOpt  = el.pathwaySelect.options[el.pathwaySelect.selectedIndex];
  const pathwayName  = selectedOpt.text;
  const sector       = selectedOpt.closest('optgroup')?.label || '';

  state.selectedPathway = { id: pathwayId, name: pathwayName, sector };
  state.activeFlow = 'flow1';

  await fetchAndRenderPositions(pathwayId, pathwayName, sector);
}

// =====================================================
//   FLOW 2 — Career → Pathway Recommendations → Positions
// =====================================================

async function onCareerChange() {
  const careerId = parseInt(el.careerSelect.value);

  hide(el.pathwayRecommendations);
  el.pathwayCards.innerHTML = '';
  clearResults();

  if (!careerId) return;

  state.activeFlow = 'flow2';

  try {
    const data     = await apiFetch(`/api/pathways/by-career/${careerId}`);
    const pathways = data.pathways;

    if (pathways.length === 0) {
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
      const moreSchools = pathway.schools.length > 3
        ? ` +${pathway.schools.length - 3} more` : '';

      card.innerHTML = `
        <div class="pathway-rec-name">${escapeHtml(pathway.name)}</div>
        <div class="pathway-rec-sector">${escapeHtml(pathway.sector || '')}</div>
        ${pathway.schools.length > 0
          ? `<div class="pathway-rec-schools">📍 ${escapeHtml(schoolList)}${moreSchools}</div>`
          : ''}
      `;

      card.addEventListener('click', () => {
        document.querySelectorAll('.pathway-rec-card')
          .forEach(c => c.classList.remove('active'));
        card.classList.add('active');

        state.selectedPathway = {
          id:     pathway.id,
          name:   pathway.name,
          sector: pathway.sector || '',
        };

        fetchAndRenderPositions(pathway.id, pathway.name, pathway.sector || '');

        if (pathway.schools.length > 0 && state.map) {
          const first = pathway.schools[0];
          if (first.latitude) {
            state.map.setView([first.latitude, first.longitude], 11);
          }
          pathway.schools.forEach(s => highlightMarker(s.id));
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
//   COUNTY POSITION FETCHING + RENDERING
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
      // Pathway has no county program tied to it yet.
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

    // Prefer the first live posting URL when one exists; fall back to the
    // catalog-level keyword-search URL (apply_url) otherwise.
    const liveUrl   = pos.is_hiring_now && pos.current_postings[0]?.url;
    const applyHref = liveUrl || pos.apply_url;
    const applyLabel = pos.is_hiring_now
      ? 'Apply now ↗'
      : (pos.apply_url ? 'See current postings ↗' : 'Not yet posting');

    const applyBtn = applyHref
      ? `<a class="position-apply-btn ${pos.is_hiring_now ? 'position-apply-btn--hiring' : ''}"
            href="${escapeHtml(applyHref)}"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="${escapeHtml(pos.is_hiring_now ? 'Apply for ' + pos.title : 'See current postings for ' + pos.title)} on governmentjobs.com">
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
  // Only render the "live postings" detail block when there are multiple
  // current postings — for a single posting the Apply button already covers it.
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
    const cls = step.is_entry ? 'ladder-step ladder-step--entry' : 'ladder-step';
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
