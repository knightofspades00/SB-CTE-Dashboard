/* =====================================================
   CTE JOB DASHBOARD — app.js
   Map: Leaflet.js + OpenStreetMap (no API key needed)
   Handles: map markers, both user flows, job results
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
  if (!str) return '';
  return str
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
  // Centre on San Bernardino County
  state.map = L.map('map').setView([34.1083, -117.2898], 10);

  // OpenStreetMap tile layer — free, no key needed
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 18,
  }).addTo(state.map);
}

function placeMarkers() {
  // Clear any existing markers
  state.markers.forEach(({ marker }) => marker.remove());
  state.markers = [];

  // Custom blue circle icon
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

  // Orange icon for selected/highlighted school
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
        <strong style="color:#0f2f54;">${school.name}</strong><br>
        <span style="font-size:12px;color:#666;">${school.district}</span><br>
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
  // Group schools by district
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
//   FLOW 1 — School → Pathway → Jobs
// =====================================================

async function onSchoolChange() {
  const schoolId = parseInt(el.schoolSelect.value);

  el.pathwaySelect.innerHTML = '<option value="">-- Choose a pathway --</option>';
  el.pathwaySelect.disabled  = true;
  clearResults();

  if (!schoolId) return;

  highlightMarker(schoolId);

  // Pan map to selected school
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

    // Group by sector
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

  await fetchAndRenderJobs(pathwayId, pathwayName, sector);
}

// =====================================================
//   FLOW 2 — Career → Pathway Recommendations → Jobs
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

        fetchAndRenderJobs(pathway.id, pathway.name, pathway.sector || '');

        // Pan map to first school offering this pathway
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
//   JOB FETCHING + RENDERING
// =====================================================

async function fetchAndRenderJobs(pathwayId, pathwayName, sector) {
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

    if (!data.api_available) {
      show(el.apiUnavailable);
      el.resultsCount.textContent = '';
      return;
    }

    if (!data.jobs || data.jobs.length === 0) {
      show(el.noResults);
      el.resultsCount.textContent = '0 jobs';
      return;
    }

    el.resultsCount.textContent   = `${data.total} job${data.total !== 1 ? 's' : ''} found`;
    el.resultsHeading.textContent = `Jobs for ${pathwayName}`;
    renderJobCards(data.jobs);

  } catch (e) {
    hide(el.loading);
    show(el.apiUnavailable);
    el.resultsCount.textContent = '';
    console.error('Failed to fetch jobs:', e);
  }
}

function renderJobCards(jobs) {
  el.resultsList.innerHTML = '';

  jobs.forEach(job => {
    const card       = document.createElement('div');
    card.className   = 'job-card';

    const postedDate = job.posted
      ? new Date(job.posted).toLocaleDateString('en-US',
          { month: 'short', day: 'numeric', year: 'numeric' })
      : null;

    card.innerHTML = `
      <div class="job-title">${escapeHtml(job.title)}</div>

      ${job.apply_url
        ? `<a class="job-apply-btn"
              href="${job.apply_url}"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Apply for ${escapeHtml(job.title)}">
              Apply ↗
           </a>`
        : '<span class="job-apply-btn" style="opacity:0.4;cursor:default;">No link</span>'
      }

      <div class="job-meta">
        <span class="job-meta-item">🏢 ${escapeHtml(job.employer || 'Federal Agency')}</span>
        ${job.location
          ? `<span class="job-meta-item">📍 ${escapeHtml(job.location)}</span>`
          : ''}
        ${job.salary
          ? `<span class="job-meta-item salary">💰 ${escapeHtml(job.salary)}</span>`
          : ''}
        ${postedDate
          ? `<span class="job-meta-item">🗓 Posted ${postedDate}</span>`
          : ''}
      </div>

      <div class="job-source-tag">Source: USAJobs.gov</div>
    `;

    el.resultsList.appendChild(card);
  });
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
  el.resultsHeading.textContent = 'Job Results';
  state.selectedPathway         = null;
}