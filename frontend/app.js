// State management
let allRecords = [];
let isPolling = false;
let pollInterval = null;

// Toast notifications
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 250);
  }, 3500);
}

// Preset format click helper
function setFormat(fmt) {
  document.getElementById('namingFormat').value = fmt;
  showToast(`Format set to: ${fmt}`);
}

// Accordion toggle
function toggleAccordion() {
  const acc = document.getElementById('advancedAccordion');
  acc.classList.toggle('open');
  const arrow = document.getElementById('accordionArrow');
  arrow.textContent = acc.classList.contains('open') ? '▲' : '▼';
}

// Copy single text
function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    showToast(`Copied: ${text}`, 'success');
  }).catch(() => {
    showToast('Failed to copy', 'error');
  });
}

// Copy all formatted handles
function copyAllFormatted() {
  if (!allRecords.length) {
    showToast('No records to copy', 'warn');
    return;
  }
  const unique = Array.from(new Set(allRecords.map(r => r.formatted).filter(Boolean)));
  navigator.clipboard.writeText(unique.join('\n')).then(() => {
    showToast(`Copied ${unique.length} unique accounts to clipboard!`, 'success');
  });
}

// Real-time table filter
function filterTable() {
  const query = document.getElementById('tableFilter').value.toLowerCase().trim();
  if (!query) {
    renderTable(allRecords);
    return;
  }
  const filtered = allRecords.filter(r => 
    (r.name && r.name.toLowerCase().includes(query)) ||
    (r.title && r.title.toLowerCase().includes(query)) ||
    (r.formatted && r.formatted.toLowerCase().includes(query)) ||
    (r.url && r.url.toLowerCase().includes(query))
  );
  renderTable(filtered);
}

// Escape HTML utility
function escapeHtml(text) {
  return (text || '').replace(/[&<>"']/g, function(m) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'}[m];
  });
}

// Render Table Rows
function renderTable(records) {
  const tbody = document.getElementById('resultsTableBody');
  const emptyState = document.getElementById('emptyState');
  tbody.innerHTML = '';

  if (!records || records.length === 0) {
    emptyState.style.display = 'block';
    return;
  }

  emptyState.style.display = 'none';

  records.forEach((r, i) => {
    const tr = document.createElement('tr');
    const engineClass = (r.engine || 'google').toLowerCase();

    tr.innerHTML = `
      <td style="color:var(--text-dim);">${i + 1}</td>
      <td class="col-name">${escapeHtml(r.name || 'Unknown')}</td>
      <td class="col-title" title="${escapeHtml(r.title || '')}">${escapeHtml(r.title || 'N/A')}</td>
      <td>
        <div class="col-formatted">
          <span>${escapeHtml(r.formatted || '-')}</span>
          ${r.formatted ? `<span class="copy-pill" onclick="copyText('${escapeHtml(r.formatted)}')">copy</span>` : ''}
        </div>
      </td>
      <td>
        <span class="engine-badge ${engineClass}">${escapeHtml(r.engine || 'web')}</span>
      </td>
      <td style="text-align:center;">
        ${r.url ? `
          <a href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer" class="link-icon" title="View LinkedIn Profile">
            <svg width="16" height="16" fill="currentColor" viewBox="0 0 24 24">
              <path d="M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/>
            </svg>
          </a>
        ` : '-'}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// Append logs to terminal console
function updateConsoleLogs(logs) {
  if (!logs || !logs.length) return;
  const consoleBody = document.getElementById('consoleBody');
  consoleBody.innerHTML = '';
  logs.forEach(l => {
    const div = document.createElement('div');
    div.className = 'log-line';
    div.innerHTML = `
      <span class="log-time">[${l.time}]</span>
      <span class="log-level-${l.level || 'info'}">${escapeHtml(l.message)}</span>
    `;
    consoleBody.appendChild(div);
  });
  consoleBody.scrollTop = consoleBody.scrollHeight;
}

function clearLogs() {
  document.getElementById('consoleBody').innerHTML = '';
}

// Header status badge
function updateHeaderStatus(isRunning, statusText) {
  const dot = document.getElementById('headerStatusDot');
  const text = document.getElementById('headerStatusText');
  const btnStart = document.getElementById('btnStartSearch');
  const btnStop = document.getElementById('btnStopSearch');

  if (isRunning) {
    dot.className = 'status-dot searching';
    text.textContent = 'Scraping in progress...';
    btnStart.disabled = true;
    btnStop.disabled = false;
  } else {
    dot.className = 'status-dot';
    text.textContent = statusText || 'Engine Idle';
    btnStart.disabled = false;
    btnStop.disabled = true;
  }
}

// Fetch results
async function fetchResults(isManual = false) {
  try {
    const res = await fetch('/api/results');
    if (!res.ok) throw new Error('API returned ' + res.status);
    const data = await res.json();
    allRecords = data.records || [];
    renderTable(allRecords);

    // Update stats cards
    document.getElementById('statTotalScraped').textContent = data.stats.total_scraped || 0;
    document.getElementById('statUniqueFormatted').textContent = data.stats.unique_formatted || 0;
    document.getElementById('statEngines').textContent = (data.stats.engines_used && data.stats.engines_used.length) ? data.stats.engines_used.join(', ').toUpperCase() : 'Google, Bing';
    document.getElementById('statStatus').textContent = data.stats.status || 'Idle';
    document.getElementById('statLastRun').textContent = data.stats.last_search_time ? `Last: ${data.stats.last_search_time}` : 'Ready';

    if (isManual) showToast('Data refreshed successfully');
  } catch (e) {
    console.error(e);
  }
}

// Status poll loop
async function pollStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const data = await res.json();

    updateHeaderStatus(data.is_running, data.stats ? data.stats.status : 'Idle');
    updateConsoleLogs(data.logs);

    if (data.stats) {
      document.getElementById('statTotalScraped').textContent = data.stats.total_scraped || 0;
      document.getElementById('statUniqueFormatted').textContent = data.stats.unique_formatted || 0;
      document.getElementById('statStatus').textContent = data.stats.status || 'Idle';
    }

    if (!data.is_running && isPolling) {
      isPolling = false;
      clearInterval(pollInterval);
      fetchResults();
      showToast('Search process completed!', 'success');
    }
  } catch (err) {
    console.error(err);
  }
}

// Start Scrape
async function startSearch() {
  const target = document.getElementById('targetCompany').value.trim();
  const format = document.getElementById('namingFormat').value.trim();
  const yahoo = document.getElementById('engineYahoo') ? document.getElementById('engineYahoo').checked : true;
  const google = document.getElementById('engineGoogle') ? document.getElementById('engineGoogle').checked : false;
  const bing = document.getElementById('engineBing') ? document.getElementById('engineBing').checked : false;
  const timeout = parseFloat(document.getElementById('timeoutInput').value) || 15;
  const jitter = parseFloat(document.getElementById('jitterInput').value) || 1;
  const outfile = document.getElementById('outfileInput').value.trim() || 'names';
  const proxies = document.getElementById('proxiesInput').value.trim();

  if (!target) {
    showToast('Please enter a target company name', 'warn');
    return;
  }
  if (!format) {
    showToast('Please provide a naming format pattern', 'warn');
    return;
  }

  const engines = [];
  if (yahoo) engines.push('yahoo');
  if (bing) engines.push('bing');
  if (google) engines.push('google');

  if (!engines.length) {
    showToast('Please select at least one search engine', 'warn');
    return;
  }

  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        target,
        format,
        engines,
        timeout,
        jitter,
        outfile,
        proxies
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Started scrape for "${target}"`, 'success');
      updateHeaderStatus(true);
      isPolling = true;
      if (pollInterval) clearInterval(pollInterval);
      pollInterval = setInterval(pollStatus, 1500);
    } else {
      showToast(data.error || data.message, 'error');
    }
  } catch (e) {
    showToast('Error initiating search: ' + e.message, 'error');
  }
}

// Stop Scrape
async function stopSearch() {
  try {
    const res = await fetch('/api/stop', {method: 'POST'});
    const data = await res.json();
    showToast(data.message, 'warn');
  } catch (e) {
    showToast('Error stopping search: ' + e.message, 'error');
  }
}

// Re-format loaded data
async function reformatData() {
  const format = document.getElementById('namingFormat').value.trim();
  if (!format) {
    showToast('Please specify a naming convention', 'warn');
    return;
  }
  try {
    const res = await fetch('/api/reformat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({format})
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      allRecords = data.records || [];
      renderTable(allRecords);
      document.getElementById('statUniqueFormatted').textContent = data.stats.unique_formatted || 0;
    } else {
      showToast(data.error || 'Failed to reformat', 'error');
    }
  } catch (e) {
    showToast('Reformat error: ' + e.message, 'error');
  }
}

// Load CSV
async function loadExistingCsv() {
  try {
    const res = await fetch('/api/load_csv', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({filename: 'names.csv'})
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Loaded ${data.records ? data.records.length : 0} records from names.csv`, 'success');
      allRecords = data.records || [];
      renderTable(allRecords);
      document.getElementById('statTotalScraped').textContent = data.stats.total_scraped || 0;
      document.getElementById('statUniqueFormatted').textContent = data.stats.unique_formatted || 0;
    }
  } catch (e) {
    showToast('Failed to load CSV: ' + e.message, 'error');
  }
}

// Clear Dashboard
async function clearDashboard() {
  if (!confirm('Are you sure you want to clear the dashboard view and logs?')) return;
  try {
    await fetch('/api/clear', {method: 'POST'});
    allRecords = [];
    renderTable([]);
    clearLogs();
    document.getElementById('statTotalScraped').textContent = 0;
    document.getElementById('statUniqueFormatted').textContent = 0;
    document.getElementById('statStatus').textContent = 'Idle';
    showToast('Dashboard cleared', 'info');
  } catch (e) {
    showToast('Error clearing: ' + e.message, 'error');
  }
}

// Init on load
window.addEventListener('DOMContentLoaded', () => {
  fetchResults();
  pollStatus();
});

