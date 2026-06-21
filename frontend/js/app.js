/**
 * OSINT Hub — Main Application
 * Manages authentication state, routing between views, and global state.
 */

// ── State ─────────────────────────────────────────────────────────────────
const State = {
  currentView: 'home',       // home | scanning | results | history
  currentScan: null,         // { id, target, targetType, status }
  wsClient: null,
  toolStatuses: {},          // { toolName: { status, found, checked } }
  summary: null,
  logLines: [],
  currentTab: 'profile',     // profile | accounts | pivot
  currentTypeFilter: 'auto', // auto | username | email | phone
  history: [],
};

// ── API Helpers ───────────────────────────────────────────────────────────
const API = {
  async post(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    });
    return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
  },

  async get(path) {
    const res = await fetch(path, { credentials: 'include' });
    if (res.status === 401) { showLogin(); return null; }
    return res.ok ? await res.json() : null;
  },

  async delete(path) {
    const res = await fetch(path, { method: 'DELETE', credentials: 'include' });
    return res.ok;
  },
};

// ── Toast ─────────────────────────────────────────────────────────────────
function toast(message, type = 'info', duration = 3500) {
  const icons = { success: '✓', error: '✗', info: 'ℹ' };
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${message}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = 'toastSlide 0.3s ease reverse forwards';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ── View Router ───────────────────────────────────────────────────────────
function showView(viewName) {
  ['view-home', 'view-scanning', 'view-results', 'view-history', 'view-compare'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
  });
  const target = document.getElementById(`view-${viewName}`);
  if (target) {
    target.classList.remove('hidden');
    target.classList.add('fade-in');
    setTimeout(() => target.classList.remove('fade-in'), 400);
  }
  State.currentView = viewName;
  updateNavState(viewName);
}

function showLogin() {
  document.getElementById('app').classList.add('hidden');
  document.getElementById('login-page').classList.remove('hidden');
}

function showApp() {
  document.getElementById('login-page').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
}

function updateNavState(view) {
  document.querySelectorAll('[data-nav]').forEach(el => {
    el.classList.toggle('active', el.dataset.nav === view);
  });
}

// ── Auth ──────────────────────────────────────────────────────────────────
async function checkAuth() {
  const result = await fetch('/auth/check', { credentials: 'include' });
  if (result.ok) {
    const data = await result.json();
    if (data.authenticated) {
      showApp();
      loadHistory();
      return true;
    }
  }
  showLogin();
  return false;
}

async function handleLogin(e) {
  e.preventDefault();
  const password = document.getElementById('password-input').value;
  const btn = document.getElementById('login-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin inline-block">↻</span> Authentification...';

  const result = await API.post('/auth/login', { password });
  if (result.ok && result.data.success) {
    showApp();
    loadHistory();
    toast('Accès autorisé', 'success');
  } else {
    toast('Mot de passe incorrect', 'error');
    document.getElementById('password-input').value = '';
    document.getElementById('password-input').classList.add('border-red-500');
    setTimeout(() => document.getElementById('password-input').classList.remove('border-red-500'), 2000);
    btn.disabled = false;
    btn.innerHTML = 'Accéder au Hub';
  }
}

async function handleLogout() {
  await API.post('/auth/logout', {});
  showLogin();
  toast('Déconnecté', 'info');
}

// ── Search ────────────────────────────────────────────────────────────────
function detectInputType(value) {
  const emailRe = /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/;
  const phoneRe = /^[\+]?\d[\d\s\-\.\(\)]{8,}$/;
  if (emailRe.test(value)) return 'email';
  if (phoneRe.test(value.replace(/\s/g, ''))) return 'phone';
  return 'username';
}

function onSearchInput(e) {
  const value = e.target.value.trim();
  if (!value || State.currentTypeFilter !== 'auto') return;

  // Auto-detect and update badge
  const detected = detectInputType(value);
  updateTypeIndicator(detected);
}

function updateTypeIndicator(type) {
  const map = {
    username: { icon: '👤', label: 'Pseudo', color: 'text-cyan' },
    email:    { icon: '✉️', label: 'Email', color: 'text-purple' },
    phone:    { icon: '📞', label: 'Téléphone', color: 'text-amber' },
  };
  const detected = document.getElementById('detected-type');
  if (!detected) return;
  const info = map[type] || map.username;
  detected.innerHTML = `${info.icon} <span class="${info.color}">${info.label} détecté</span>`;
  detected.classList.remove('hidden');
}

async function handleSearch(e) {
  e.preventDefault();
  const target = document.getElementById('search-input').value.trim();
  if (!target) { toast('Saisir une cible', 'error'); return; }

  const targetType = State.currentTypeFilter === 'auto'
    ? detectInputType(target)
    : State.currentTypeFilter;

  // Reset state
  State.toolStatuses = {};
  State.summary = null;
  State.logLines = [];
  State.currentTab = 'profile';

  // Launch scan
  const result = await API.post('/api/scan', { target, target_type: targetType });
  if (!result.ok) {
    toast('Erreur lors du lancement du scan', 'error');
    return;
  }

  const scan = result.data;
  State.currentScan = {
    id: scan.scan_id,
    target: scan.target,
    targetType: scan.target_type,
    status: 'running',
  };

  // Initialize tool statuses from response
  (scan.tools || []).forEach(t => {
    State.toolStatuses[t.tool_name] = { status: 'pending', found: 0, checked: 0 };
  });

  // Show scanning view
  showView('scanning');
  renderScanningView(scan);

  // Connect WebSocket
  if (State.wsClient) State.wsClient.close();
  State.wsClient = new OSINTWebSocket(scan.scan_id);
  State.wsClient
    .on('tool_update', onToolUpdate)
    .on('scan_complete', onScanComplete)
    .on('scan_failed', onScanFailed)
    .on('scan_started', onScanStarted)
    .on('email_discovered', onEmailDiscovered)
    .on('connected', () => toast(`Scan lancé sur "${target}"`, 'info'));

  State.wsClient.connect();
}

// ── WebSocket Event Handlers ──────────────────────────────────────────────
function onScanStarted(data) {
  addLog(`🔍 Investigation démarrée — Cible: ${data.target} (${data.target_type})`, 'info');
}

function onToolUpdate(data) {
  const { tool, status, sites_found, sites_checked } = data;
  State.toolStatuses[tool] = { status, found: sites_found, checked: sites_checked };

  updateToolCard(tool, { status, found: sites_found, checked: sites_checked });

  const label = { running: '⚡', completed: '✓', failed: '✗', skipped: '⊘' }[status] || '…';
  addLog(`${label} ${tool}: ${status} (${sites_found}/${sites_checked} sites)`,
    status === 'completed' ? 'found' : status === 'failed' ? 'error' : 'info');
}

function onScanComplete(data) {
  State.summary = data.summary;
  State.currentScan.status = 'completed';
  addLog(`✅ Scan terminé — ${data.summary.total_accounts} comptes trouvés`, 'found');

  // Transition to results after brief delay
  setTimeout(() => {
    showView('results');
    renderResultsView(data.summary);
    loadHistory(); // refresh history
  }, 800);
}

function onScanFailed(data) {
  State.currentScan.status = 'failed';
  addLog(`❌ Scan échoué: ${data.error}`, 'error');
  toast('Scan échoué', 'error');
}

function onEmailDiscovered(data) {
  addLog(`📧 Email découvert: ${data.email} (via ${data.source})`, 'found');
  toast(`Email découvert: ${data.email}`, 'success');
}

// ── Scanning View ─────────────────────────────────────────────────────────
function renderScanningView(scan) {
  document.getElementById('scanning-target').textContent = scan.target;
  document.getElementById('scanning-type').textContent = scan.target_type;

  const container = document.getElementById('tool-cards');
  if (!container) return;
  container.innerHTML = '';

  const toolMeta = {
    maigret:      { icon: '🔭', label: 'Maigret',     desc: 'Analyse profonde + métadonnées' },
    sherlock:     { icon: '🕵️', label: 'Sherlock',    desc: 'Scan rapide 400+ sites' },
    whatsmyname:  { icon: '🔎', label: 'WhatsMyName',  desc: 'Scan concurrent 600+ sites' },
    holehe:       { icon: '🔑', label: 'Holehe',       desc: 'Vérification email 120+ services' },
    ghunt:        { icon: '🌐', label: 'GHunt',        desc: 'Intelligence Google/Gmail' },
    hibp:         { icon: '🔓', label: 'HIBP Check',   desc: 'Vérification fuites de données' },
    scraper:      { icon: '🕸️', label: 'Web Scraper', desc: 'Extraction emails & liens' },
    phone_lookup: { icon: '📞', label: 'Phone Lookup', desc: 'Recherche numéro de téléphone' },
  };

  (scan.tools || []).forEach(tool => {
    const meta = toolMeta[tool.tool_name] || { icon: '🔧', label: tool.tool_name, desc: '' };
    const card = document.createElement('div');
    card.id = `tool-card-${tool.tool_name}`;
    card.className = 'tool-card';
    card.innerHTML = `
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-3">
          <span class="text-2xl">${meta.icon}</span>
          <div>
            <div class="font-semibold text-sm">${meta.label}</div>
            <div class="text-xs text-secondary">${meta.desc}</div>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <div id="dot-${tool.tool_name}" class="status-dot pending"></div>
          <span id="status-label-${tool.tool_name}" class="text-xs text-dim font-mono">En attente</span>
        </div>
      </div>
      <div class="progress-bar" id="progress-bar-${tool.tool_name}">
        <div class="progress-fill" id="progress-fill-${tool.tool_name}" style="width: 0%"></div>
      </div>
      <div class="flex justify-between mt-2 text-xs font-mono text-dim">
        <span id="progress-text-${tool.tool_name}">0 / 0</span>
        <span id="progress-pct-${tool.tool_name}">0%</span>
      </div>
    `;
    container.appendChild(card);
  });

  // Clear log
  document.getElementById('scan-log').innerHTML = '';
}

function updateToolCard(toolName, { status, found, checked }) {
  const card = document.getElementById(`tool-card-${toolName}`);
  if (!card) return;

  // Update class
  card.className = `tool-card ${status}`;

  // Update dot
  const dot = document.getElementById(`dot-${toolName}`);
  if (dot) dot.className = `status-dot ${status}`;

  // Update label
  const label = document.getElementById(`status-label-${toolName}`);
  const labelMap = {
    pending: 'En attente', running: 'En cours...', completed: 'Terminé',
    failed: 'Échec', skipped: 'Non configuré',
  };
  if (label) label.textContent = labelMap[status] || status;

  // Update progress
  if (checked > 0) {
    const pct = Math.min(100, Math.round((found / checked) * 100));
    const fill = document.getElementById(`progress-fill-${toolName}`);
    if (fill) fill.style.width = `${Math.max(pct, 5)}%`;
    const text = document.getElementById(`progress-text-${toolName}`);
    if (text) text.textContent = `${found} / ${checked}`;
    const pctEl = document.getElementById(`progress-pct-${toolName}`);
    if (pctEl) pctEl.textContent = `${pct}%`;
  }

  if (status === 'completed') {
    const fill = document.getElementById(`progress-fill-${toolName}`);
    if (fill) fill.style.width = '100%';
  }
}

function addLog(message, type = 'info') {
  State.logLines.push({ message, type });
  const log = document.getElementById('scan-log');
  if (!log) return;

  const line = document.createElement('div');
  line.className = `log-line ${type}`;
  const time = new Date().toLocaleTimeString('fr-FR');
  line.textContent = `[${time}] ${message}`;
  log.appendChild(line);

  // Keep last 100 lines
  while (log.children.length > 100) log.firstChild.remove();
  log.scrollTop = log.scrollHeight;
}

// ── Results View ──────────────────────────────────────────────────────────
function renderResultsView(summary) {
  if (!summary) return;

  // Header
  document.getElementById('results-target').textContent =
    State.currentScan?.target || '';
  document.getElementById('results-total').textContent =
    `${summary.total_accounts} comptes trouvés`;

  // Render all tabs
  renderProfileTab(summary);
  renderAccountsTab(summary.accounts || []);
  renderPivotTab(summary);

  // Show first tab
  switchTab('profile');
}

function switchTab(tabName) {
  State.currentTab = tabName;

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  document.querySelectorAll('.tab-content').forEach(el => {
    el.classList.add('hidden');
  });
  const content = document.getElementById(`tab-${tabName}`);
  if (content) {
    content.classList.remove('hidden');
    content.classList.add('fade-in');
    setTimeout(() => content.classList.remove('fade-in'), 400);
  }

  if (tabName === 'graph' && State.summary) {
    // Render the Vis.js dynamic network graph
    setTimeout(() => renderRelationGraph(State.summary), 50);
  }
}

function renderProfileTab(summary) {
  const container = document.getElementById('tab-profile');
  if (!container) return;

  const confidence = Math.round((summary.confidence_score || 0) * 100);
  const circumference = 2 * Math.PI * 44;
  const offset = circumference - (confidence / 100) * circumference;

  // Render phone lookup metadata if valid
  let phoneHtml = '';
  if (summary.phone_metadata && summary.phone_metadata.valid) {
    const meta = summary.phone_metadata;
    phoneHtml = `
      <div class="glass-card p-5 mb-6">
        <div class="text-xs uppercase tracking-widest text-secondary mb-3 flex items-center gap-2">
          <span>📞</span> Informations Numéro de Téléphone
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm font-mono">
          <div><span class="text-dim">Format E.164:</span> <span class="text-cyan">${meta.e164}</span></div>
          <div><span class="text-dim">International:</span> <span class="text-primary">${meta.international}</span></div>
          <div><span class="text-dim">Opérateur:</span> <span class="text-purple">${meta.carrier}</span></div>
          <div><span class="text-dim">Localisation:</span> <span class="text-green">${meta.location}</span></div>
          <div><span class="text-dim">Fuseaux Horaires:</span> <span class="text-primary">${(meta.timezones || []).join(', ')}</span></div>
        </div>
      </div>
    `;
  }

  // Render HaveIBeenPwned leaks if any
  let breachesHtml = '';
  if (summary.breaches && summary.breaches.length > 0) {
    breachesHtml = `
      <div class="glass-card p-5 mb-6">
        <div class="text-xs uppercase tracking-widest text-red-400 mb-3 flex items-center gap-2">
          <span>⚠️</span> Violations de Données (HIBP Leaks)
        </div>
        <div class="flex flex-col gap-4">
          ${summary.breaches.map(b => `
            <div class="border-b border-white/5 pb-3 last:border-0 last:pb-0">
              <div class="flex justify-between flex-wrap gap-2 mb-1">
                <span class="font-bold text-sm text-red-400">${b.name} (${b.domain})</span>
                <span class="text-xs font-mono text-dim">${b.date}</span>
              </div>
              <p class="text-xs text-secondary mb-2">${b.details}</p>
              <div class="flex flex-wrap gap-1">
                ${(b.data_classes || []).map(dc => `
                  <span class="tag-badge" style="font-size: 9px; padding: 2px 6px; background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.25); color: #ef4444;">
                    ${dc}
                  </span>
                `).join('')}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  // Render timeline if available
  let timelineHtml = '';
  if (summary.timeline && summary.timeline.length > 0) {
    timelineHtml = `
      <div class="glass-card p-5 mb-6">
        <div class="text-xs uppercase tracking-widest text-secondary mb-3 flex items-center gap-2">
          <span>📅</span> Timeline d'Activité OSINT
        </div>
        <div class="timeline-container">
          ${summary.timeline.map(item => `
            <div class="timeline-item">
              <div class="timeline-date">${item.date}</div>
              <div class="timeline-event">${item.event}</div>
              <div class="timeline-source">${item.source}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  // Render notes and tags editor
  const tagsStr = (State.currentScan?.tags || []).join(', ');
  const notesStr = State.currentScan?.notes || '';
  const metadataHtml = `
    <div class="glass-card p-5 mb-6 no-print">
      <div class="text-xs uppercase tracking-widest text-secondary mb-4 flex items-center justify-between">
        <span>📝 Notes d'Investigation & Étiquettes</span>
        <span class="text-dim">Persistant</span>
      </div>
      <div class="flex flex-col gap-4">
        <div>
          <label class="text-xs text-secondary block mb-1">Étiquettes (séparées par des virgules)</label>
          <input id="scan-tags-input" type="text" class="form-input text-sm" placeholder="ex: suspect, priorite-haute, faux-positif" value="${tagsStr}" />
        </div>
        <div>
          <label class="text-xs text-secondary block mb-1">Remarques & Observations</label>
          <textarea id="scan-notes-input" class="form-input text-sm h-24" placeholder="Saisir des notes libres sur cette cible...">${notesStr}</textarea>
        </div>
        <div class="flex justify-end">
          <button id="save-metadata-btn" class="btn-primary text-xs py-2 px-4" onclick="saveScanMetadata()">
            💾 Enregistrer les notes
          </button>
        </div>
      </div>
    </div>
  `;

  container.innerHTML = `
    <!-- Identity Card -->
    <div class="glass-card glass-card-glow p-6 mb-6 slide-up">
      <div class="flex items-center gap-6 flex-wrap">
        <!-- Avatar -->
        <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-cyan-500 to-purple-600 
                    flex items-center justify-center text-3xl flex-shrink-0 shadow-lg"
             style="box-shadow: 0 0 30px rgba(0,212,255,0.3)">
          🕵️
        </div>
        <!-- Info -->
        <div class="flex-1 min-w-0">
          <div class="text-xs uppercase tracking-widest text-secondary mb-1">Meilleure estimation</div>
          <div class="text-2xl font-bold gradient-text mb-1">
            ${summary.top_identity_guess || 'Identité inconnue'}
          </div>
          <div class="text-sm text-secondary">
            Cible: <span class="text-primary font-mono">${State.currentScan?.target || ''}</span>
            &nbsp;·&nbsp;
            <span class="text-${State.currentScan?.targetType === 'email' ? 'purple' : 'cyan'}">
              ${State.currentScan?.targetType || ''}
            </span>
          </div>
          ${State.currentScan?.tags && State.currentScan.tags.length > 0 ? `
            <div class="flex flex-wrap gap-1.5 mt-2">
              ${State.currentScan.tags.map(t => `<span class="tag-badge compare-tag">${t}</span>`).join('')}
            </div>
          ` : ''}
        </div>
        <!-- Confidence Ring -->
        <div class="confidence-ring flex-shrink-0">
          <svg viewBox="0 0 100 100" width="96" height="96">
            <defs>
              <linearGradient id="ringGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color:#00d4ff"/>
                <stop offset="100%" style="stop-color:#7c3aed"/>
              </linearGradient>
            </defs>
            <circle cx="50" cy="50" r="44" class="ring-track"/>
            <circle cx="50" cy="50" r="44" class="ring-fill"
              stroke-dasharray="${circumference}"
              stroke-dashoffset="${offset}"
            />
          </svg>
          <div class="confidence-label">
            <span>${confidence}%</span>
            <span style="font-size:10px;color:var(--text-secondary);font-weight:400;">confiance</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Phone Info (Conditional) -->
    ${phoneHtml}

    <!-- HaveIBeenPwned Leaks (Conditional) -->
    ${breachesHtml}

    <!-- Entity Chips Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
      <!-- Prénoms -->
      <div class="glass-card p-5">
        <div class="text-xs uppercase tracking-widest text-secondary mb-3 flex items-center gap-2">
          <span>👤</span> Prénoms détectés
        </div>
        <div class="flex flex-wrap gap-2">
          ${Object.entries(summary.firstnames || {}).sort((a,b) => b[1]-a[1])
            .slice(0, 8).map(([name, count]) => `
            <div class="stat-chip">
              <span>${name}</span>
              <span class="count">×${count}</span>
            </div>`).join('') || '<span class="text-dim text-sm">Aucun détecté</span>'}
        </div>
      </div>

      <!-- Localisations -->
      <div class="glass-card p-5">
        <div class="text-xs uppercase tracking-widest text-secondary mb-3 flex items-center gap-2">
          <span>📍</span> Localisations probables
        </div>
        <div class="flex flex-wrap gap-2">
          ${Object.entries(summary.locations || {}).sort((a,b) => b[1]-a[1])
            .slice(0, 8).map(([loc, count]) => `
            <div class="stat-chip">
              <span>${loc}</span>
              <span class="count">×${count}</span>
            </div>`).join('') || '<span class="text-dim text-sm">Aucune détectée</span>'}
        </div>
      </div>

      <!-- Emails trouvés -->
      ${(summary.emails_found || []).length > 0 ? `
      <div class="glass-card p-5">
        <div class="text-xs uppercase tracking-widest text-secondary mb-3 flex items-center gap-2">
          <span>✉️</span> Emails découverts
        </div>
        <div class="flex flex-col gap-2">
          ${(summary.emails_found || []).map(email => `
          <div class="flex items-center justify-between">
            <span class="font-mono text-sm text-cyan">${email}</span>
            <button onclick="pivotOnEmail('${email}')" 
                    class="pivot-btn text-xs px-3 py-1">
              🔄 Pivoter
            </button>
          </div>`).join('')}
        </div>
      </div>` : ''}

      <!-- Mots-clés bio -->
      ${Object.keys(summary.bio_keywords || {}).length > 0 ? `
      <div class="glass-card p-5">
        <div class="text-xs uppercase tracking-widest text-secondary mb-3 flex items-center gap-2">
          <span>🏷️</span> Mots-clés biographie
        </div>
        <div class="flex flex-wrap gap-2">
          ${Object.entries(summary.bio_keywords || {}).sort((a,b) => b[1]-a[1])
            .slice(0, 12).map(([kw, count]) => `
            <div class="stat-chip" style="font-size:12px;opacity:${Math.max(0.5, count/5)}">
              <span>${kw}</span>
              <span class="count">×${count}</span>
            </div>`).join('')}
        </div>
      </div>` : ''}
    </div>

    <!-- Timeline & Notes -->
    ${timelineHtml}
    ${metadataHtml}
  `;
}

function renderAccountsTab(accounts) {
  const container = document.getElementById('tab-accounts');
  if (!container) return;

  if (!accounts.length) {
    container.innerHTML = `
      <div class="text-center py-16 text-secondary">
        <div class="text-4xl mb-4">🔍</div>
        <div class="text-lg font-medium">Aucun compte trouvé</div>
        <div class="text-sm mt-2">Les outils n'ont pas trouvé de profils publics</div>
      </div>`;
    return;
  }

  // Group by category
  const byCategory = {};
  accounts.forEach(acc => {
    const cat = acc.category || 'other';
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(acc);
  });

  const categoryLabels = {
    social: '📱 Réseaux Sociaux', gaming: '🎮 Gaming', tech: '💻 Tech & Dev',
    forum: '💬 Forums', music: '🎵 Musique', media: '📺 Médias',
    dating: '❤️ Dating', professional: '💼 Professionnel', other: '🌐 Autres',
  };

  const categoryOrder = ['social', 'gaming', 'tech', 'forum', 'professional',
                          'music', 'media', 'dating', 'other'];

  let html = `
    <div class="flex items-center justify-between mb-4">
      <div class="text-sm text-secondary">
        ${accounts.length} compte${accounts.length > 1 ? 's' : ''} trouvé${accounts.length > 1 ? 's' : ''}
      </div>
      <button onclick="exportAccounts()" class="btn-secondary text-xs py-2">
        ↓ Exporter JSON
      </button>
    </div>`;

  categoryOrder.forEach(cat => {
    const catAccounts = byCategory[cat];
    if (!catAccounts || !catAccounts.length) return;

    html += `
      <div class="mb-6">
        <h3 class="text-sm font-semibold text-secondary uppercase tracking-widest mb-3 
                   flex items-center gap-2">
          ${categoryLabels[cat] || cat}
          <span class="bg-white/10 text-primary px-2 py-0.5 rounded text-xs font-mono">
            ${catAccounts.length}
          </span>
        </h3>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          ${catAccounts.map(acc => renderAccountCard(acc)).join('')}
        </div>
      </div>`;
  });

  container.innerHTML = html;
}

function renderAccountCard(acc) {
  const favicon = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(
    new URL(acc.url).hostname
  )}&sz=32`;

  return `
    <a href="${acc.url}" target="_blank" rel="noopener noreferrer" class="account-card">
      <div class="account-favicon">
        <img src="${favicon}" width="20" height="20"
             onerror="this.style.display='none';this.nextElementSibling.style.display='block'"
             alt="">
        <span style="display:none">🔗</span>
      </div>
      <div class="flex-1 min-w-0">
        <div class="font-medium text-sm truncate">${acc.site_name}</div>
        <div class="text-xs text-secondary truncate">${acc.url}</div>
      </div>
      <div>
        <span class="cat-badge cat-${acc.category || 'other'}">
          ${acc.source_tool}
        </span>
      </div>
    </a>`;
}

function renderPivotTab(summary) {
  const container = document.getElementById('tab-pivot');
  if (!container) return;

  const emails = summary.emails_found || [];
  const accounts = (summary.accounts || []).filter(a =>
    ['social', 'gaming', 'tech'].includes(a.category)
  ).slice(0, 6);

  let html = '';

  if (emails.length > 0) {
    html += `
      <div class="mb-6">
        <h3 class="text-sm font-semibold uppercase tracking-widest text-secondary mb-3">
          📧 Pivot sur Email
        </h3>
        <div class="flex flex-col gap-3">
          ${emails.map(email => `
          <div class="pivot-card">
            <div class="flex items-center justify-between flex-wrap gap-3">
              <div>
                <div class="font-mono text-cyan text-sm mb-1">${email}</div>
                <div class="text-xs text-secondary">
                  Relancer une investigation complète axée sur cet email
                </div>
              </div>
              <button onclick="pivotOnEmail('${email}')" class="pivot-btn">
                🔄 Pivoter sur cet email
              </button>
            </div>
          </div>`).join('')}
        </div>
      </div>`;
  }

  if (accounts.length > 0) {
    html += `
      <div class="mb-6">
        <h3 class="text-sm font-semibold uppercase tracking-widest text-secondary mb-3">
          🔗 Comptes clés (accès rapide)
        </h3>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          ${accounts.map(acc => `
          <div class="pivot-card cursor-pointer" onclick="window.open('${acc.url}', '_blank')">
            <div class="font-semibold text-sm mb-1">${acc.site_name}</div>
            <div class="text-xs text-secondary truncate font-mono">${acc.url}</div>
          </div>`).join('')}
        </div>
      </div>`;
  }

  if (!emails.length && !accounts.length) {
    html = `
      <div class="text-center py-16 text-secondary">
        <div class="text-4xl mb-4">🔄</div>
        <div class="text-lg font-medium">Aucun pivot disponible</div>
        <div class="text-sm mt-2">Des emails ou comptes supplémentaires sont nécessaires pour pivoter</div>
      </div>`;
  }

  container.innerHTML = html;
}

function pivotOnEmail(email) {
  document.getElementById('search-input').value = email;
  State.currentTypeFilter = 'email';
  document.querySelectorAll('.type-badge').forEach(b => b.classList.remove('active'));
  document.querySelector('[data-type="email"]')?.classList.add('active');
  updateTypeIndicator('email');
  showView('home');
  toast(`Pivot sur ${email} — Lancer la recherche`, 'info');
}

function exportAccounts() {
  if (!State.summary?.accounts) return;
  const data = JSON.stringify(State.summary.accounts, null, 2);
  const blob = new Blob([data], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `osint_${State.currentScan?.target}_accounts.json`;
  a.click();
  URL.revokeObjectURL(url);
  toast('Export JSON téléchargé', 'success');
}

// ── History View ──────────────────────────────────────────────────────────
async function loadHistory() {
  const data = await API.get('/api/history?limit=20');
  if (!data) return;
  State.history = data;
  renderHistory(data);
}

function renderHistory(items) {
  const container = document.getElementById('history-list');
  if (!container) return;

  if (!items.length) {
    container.innerHTML = `
      <div class="text-center py-16 text-secondary">
        <div class="text-4xl mb-4">📋</div>
        <div>Aucun scan dans l'historique</div>
      </div>`;
    return;
  }

  container.innerHTML = items.map(item => {
    const statusColor = {
      completed: 'text-green', running: 'text-cyan blink',
      failed: 'text-red', pending: 'text-amber',
    }[item.status] || 'text-secondary';

    const typeIcon = { username: '👤', email: '✉️', phone: '📞' }[item.target_type] || '🔍';
    const date = new Date(item.created_at).toLocaleString('fr-FR');

    return `
      <div class="glass-card p-4 flex items-center gap-4 cursor-pointer 
                  hover:border-white/10 transition-all"
           onclick="viewHistoryScan('${item.scan_id}')">
        <span class="text-2xl">${typeIcon}</span>
        <div class="flex-1 min-w-0">
          <div class="font-semibold font-mono truncate">${item.target}</div>
          <div class="text-xs text-secondary mt-0.5">${date}</div>
        </div>
        <div class="text-right flex-shrink-0">
          <div class="${statusColor} text-sm font-semibold capitalize">${item.status}</div>
          ${item.total_accounts > 0 ?
            `<div class="text-xs text-secondary">${item.total_accounts} comptes</div>` : ''}
        </div>
        <button onclick="event.stopPropagation(); deleteScan('${item.scan_id}')"
                class="text-dim hover:text-red transition-colors text-lg ml-2">✕</button>
      </div>`;
  }).join('');
}

async function viewHistoryScan(scanId) {
  const scan = await API.get(`/api/scan/${scanId}`);
  if (!scan) return;

  State.currentScan = {
    id: scan.scan_id,
    target: scan.target,
    targetType: scan.target_type,
    status: scan.status,
  };
  State.summary = scan.summary;

  showView('results');
  if (scan.summary) {
    renderResultsView(scan.summary);
  } else {
    document.getElementById('results-target').textContent = scan.target;
    document.getElementById('results-total').textContent = `Statut: ${scan.status}`;
  }
}

async function deleteScan(scanId) {
  const ok = await API.delete(`/api/scan/${scanId}`);
  if (ok) {
    toast('Scan supprimé', 'success');
    loadHistory();
  }
}

// ── Init ──────────────────────────────────────────────────────────────────
function init() {
  // Auth listeners
  document.getElementById('login-form')?.addEventListener('submit', handleLogin);
  document.getElementById('logout-btn')?.addEventListener('click', handleLogout);

  // Search form
  document.getElementById('search-form')?.addEventListener('submit', handleSearch);
  document.getElementById('search-input')?.addEventListener('input', onSearchInput);

  // Type filter badges
  document.querySelectorAll('[data-type]').forEach(btn => {
    btn.addEventListener('click', () => {
      State.currentTypeFilter = btn.dataset.type;
      document.querySelectorAll('[data-type]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const input = document.getElementById('search-input').value.trim();
      if (input && btn.dataset.type !== 'auto') updateTypeIndicator(btn.dataset.type);
    });
  });

  // Navigation
  document.querySelectorAll('[data-nav]').forEach(btn => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.nav;
      if (view === 'history') loadHistory();
      if (view === 'compare') loadCompareDropdowns();
      showView(view);
    });
  });

  // Tab buttons
  document.querySelectorAll('[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Password toggle visibility
  document.getElementById('toggle-password')?.addEventListener('click', () => {
    const input = document.getElementById('password-input');
    input.type = input.type === 'password' ? 'text' : 'password';
  });

  // Compare run button
  document.getElementById('compare-run-btn')?.addEventListener('click', runComparison);

  // Check auth state
  checkAuth();
}

// ── Vis.js Relation Graph ──────────────────────────────────────────────────
let relationNetwork = null;

function renderRelationGraph(summary) {
  const container = document.getElementById('relation-graph');
  if (!container) return;

  const target = State.currentScan?.target || 'Cible';
  const accounts = summary.accounts || [];

  const nodes = [];
  const edges = [];

  // 1. Center target node
  nodes.push({
    id: 'target',
    label: target,
    title: `Cible principale`,
    size: 26,
    font: { color: '#00d4ff', face: 'JetBrains Mono', size: 14, bold: true },
    color: { border: '#00d4ff', background: '#080b14', highlight: '#00d4ff' },
    shape: 'dot'
  });

  // Categories mapping
  const categoryNodes = {
    social: { id: 'cat-social', label: 'Réseaux Sociaux', icon: '📱', color: '#60a5fa' },
    gaming: { id: 'cat-gaming', label: 'Gaming', icon: '🎮', color: '#a78bfa' },
    tech: { id: 'cat-tech', label: 'Tech & Dev', icon: '💻', color: '#34d399' },
    forum: { id: 'cat-forum', label: 'Forums', icon: '💬', color: '#fbbf24' },
    music: { id: 'cat-music', label: 'Musique', icon: '🎵', color: '#f472b6' },
    media: { id: 'cat-media', label: 'Médias', icon: '📺', color: '#f87171' },
    dating: { id: 'cat-dating', label: 'Dating', icon: '❤️', color: '#fb7185' },
    professional: { id: 'cat-professional', label: 'Pro', icon: '💼', color: '#38bdf8' },
    other: { id: 'cat-other', label: 'Autres', icon: '🌐', color: '#94a3b8' }
  };

  const activeCategories = new Set();

  accounts.forEach((acc, idx) => {
    const cat = acc.category || 'other';
    activeCategories.add(cat);

    // Account node
    const nodeId = `acc-${idx}`;
    const hostname = new URL(acc.url).hostname;
    const favicon = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(hostname)}&sz=64`;

    nodes.push({
      id: nodeId,
      label: acc.site_name,
      title: `${acc.site_name}\n${acc.url}`,
      shape: 'image',
      image: favicon,
      size: 16,
      font: { color: '#f0f4ff', size: 11 },
      color: { border: '#222', background: '#0d1224' }
    });

    // Edge from Category node to Account node
    edges.push({
      from: `cat-${cat}`,
      to: nodeId,
      color: { color: '#444', highlight: '#777' },
      width: 1
    });
  });

  // Push active categories and draw edges to center target
  activeCategories.forEach(cat => {
    const info = categoryNodes[cat] || categoryNodes.other;
    nodes.push({
      id: info.id,
      label: `${info.icon} ${info.label}`,
      size: 20,
      font: { color: info.color, size: 12, bold: true },
      color: { border: info.color, background: '#080b14' },
      shape: 'dot'
    });

    edges.push({
      from: 'target',
      to: info.id,
      color: { color: info.color, opacity: 0.6 },
      width: 2,
      length: 120
    });
  });

  // Dotted edges for extracted metadata correlations (Prénoms, localisations)
  const firstnames = Object.keys(summary.firstnames || {}).slice(0, 2);
  const locations = Object.keys(summary.locations || {}).slice(0, 2);

  firstnames.forEach((fn, idx) => {
    const nodeId = `fn-${idx}`;
    nodes.push({
      id: nodeId,
      label: `👤 ${fn}`,
      shape: 'box',
      font: { color: '#00d4ff', size: 10 },
      color: { border: 'rgba(0, 212, 255, 0.3)', background: 'rgba(0, 212, 255, 0.05)' }
    });
    edges.push({ from: 'target', to: nodeId, dashes: true, color: '#00d4ff', opacity: 0.5 });
  });

  locations.forEach((loc, idx) => {
    const nodeId = `loc-${idx}`;
    nodes.push({
      id: nodeId,
      label: `📍 ${loc}`,
      shape: 'box',
      font: { color: '#a78bfa', size: 10 },
      color: { border: 'rgba(124, 58, 237, 0.3)', background: 'rgba(124, 58, 237, 0.05)' }
    });
    edges.push({ from: 'target', to: nodeId, dashes: true, color: '#a78bfa', opacity: 0.5 });
  });

  const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
  const options = {
    physics: {
      barnesHut: {
        gravitationalConstant: -1500,
        centralGravity: 0.2,
        springLength: 95,
        springConstant: 0.04
      },
      solver: 'barnesHut'
    },
    interaction: {
      hover: true,
      zoomView: true,
      dragView: true
    }
  };

  if (relationNetwork) relationNetwork.destroy();
  relationNetwork = new vis.Network(container, data, options);
}

// ── Metadata Save REST ──────────────────────────────────────────────────────
async function saveScanMetadata() {
  const scanId = State.currentScan?.id;
  if (!scanId) return;

  const notes = document.getElementById('scan-notes-input').value;
  const tagsInput = document.getElementById('scan-tags-input').value;
  const tags = tagsInput.split(',').map(t => t.trim()).filter(t => t.length > 0);

  const btn = document.getElementById('save-metadata-btn');
  btn.disabled = true;
  btn.textContent = 'Enregistrement...';

  const res = await fetch(`/api/scan/${scanId}/metadata`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ notes, tags }),
  });

  if (res.ok) {
    const updated = await res.json();
    State.currentScan.notes = updated.notes;
    State.currentScan.tags = updated.tags;
    toast('Notes et étiquettes enregistrées', 'success');
    
    // Rerender profile tab to show tags immediately
    if (State.summary) renderProfileTab(State.summary);
  } else {
    toast("Erreur lors de l'enregistrement", 'error');
  }
  btn.disabled = false;
  btn.textContent = '💾 Enregistrer les notes';
}

// ── Comparison Logic ───────────────────────────────────────────────────────
async function loadCompareDropdowns() {
  const selectA = document.getElementById('compare-select-a');
  const selectB = document.getElementById('compare-select-b');
  if (!selectA || !selectB) return;

  // Refresh history
  await loadHistory();

  const options = ['<option value="">Sélectionner une cible...</option>'];
  State.history.forEach(item => {
    options.push(`<option value="${item.scan_id}">${item.target} (${item.target_type})</option>`);
  });

  selectA.innerHTML = options.join('');
  selectB.innerHTML = options.join('');
  
  // Hide results card if open
  document.getElementById('compare-results').classList.add('hidden');
}

async function runComparison() {
  const scanIdA = document.getElementById('compare-select-a').value;
  const scanIdB = document.getElementById('compare-select-b').value;
  
  if (!scanIdA || !scanIdB) {
    toast('Veuillez sélectionner deux scans', 'error');
    return;
  }
  if (scanIdA === scanIdB) {
    toast('Sélectionnez deux scans différents', 'error');
    return;
  }

  const btn = document.getElementById('compare-run-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin inline-block">↻</span> Comparaison...';

  const scanA = await API.get(`/api/scan/${scanIdA}`);
  const scanB = await API.get(`/api/scan/${scanIdB}`);

  if (!scanA || !scanB || !scanA.summary || !scanB.summary) {
    toast("Données de scan incomplètes ou indisponibles", 'error');
    btn.disabled = false;
    btn.textContent = '⚡ Lancer le recoupement';
    return;
  }

  renderComparison(scanA, scanB);
  
  btn.disabled = false;
  btn.textContent = '⚡ Lancer le recoupement';
}

function renderComparison(scanA, scanB) {
  const container = document.getElementById('compare-results');
  if (!container) return;

  const sumA = scanA.summary;
  const sumB = scanB.summary;

  // Correlation matches
  const commonFirstnames = Object.keys(sumA.firstnames || {}).filter(fn => 
    Object.keys(sumB.firstnames || {}).includes(fn)
  );

  const commonLocations = Object.keys(sumA.locations || {}).filter(loc => 
    Object.keys(sumB.locations || {}).includes(loc)
  );

  const commonEmails = (sumA.emails_found || []).filter(e => 
    (sumB.emails_found || []).includes(e)
  );

  const sitesA = new Set((sumA.accounts || []).map(a => a.site_name));
  const sitesB = new Set((sumB.accounts || []).map(a => a.site_name));
  const commonPlatforms = [...sitesA].filter(site => sitesB.has(site));

  let html = `
    <div class="glass-card p-6">
      <h3 class="text-lg font-bold mb-4 gradient-text">Résultats du recoupement</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <div class="text-sm font-semibold text-secondary uppercase mb-2">Scan A: ${scanA.target}</div>
          <div class="text-xs text-dim mb-4">Type: ${scanA.target_type} · ${sumA.total_accounts} comptes trouvés</div>
        </div>
        <div>
          <div class="text-sm font-semibold text-secondary uppercase mb-2">Scan B: ${scanB.target}</div>
          <div class="text-xs text-dim mb-4">Type: ${scanB.target_type} · ${sumB.total_accounts} comptes trouvés</div>
        </div>
      </div>
  `;

  if (commonFirstnames.length || commonLocations.length || commonEmails.length || commonPlatforms.length) {
    html += `
      <div class="mt-6 border-t border-white/5 pt-6">
        <h4 class="text-sm font-semibold text-secondary uppercase tracking-widest mb-4">Matches & Corrélations</h4>
        
        <div class="flex flex-col gap-4">
          ${commonEmails.map(email => `
            <div class="correlation-match-card">
              <div class="text-green font-bold text-sm mb-1">✉️ Adresse Email Identique</div>
              <div class="font-mono text-xs text-primary">${email}</div>
            </div>
          `).join('')}

          ${commonFirstnames.map(fn => `
            <div class="correlation-match-card">
              <div class="text-green font-bold text-sm mb-1">👤 Prénom Similaire</div>
              <div class="text-xs text-primary">${fn}</div>
            </div>
          `).join('')}

          ${commonLocations.map(loc => `
            <div class="correlation-match-card">
              <div class="text-green font-bold text-sm mb-1">📍 Localisation Partagée</div>
              <div class="text-xs text-primary">${loc}</div>
            </div>
          `).join('')}

          ${commonPlatforms.length > 0 ? `
            <div class="correlation-match-card">
              <div class="text-green font-bold text-sm mb-1">📱 Présence sur les mêmes plateformes</div>
              <div class="flex flex-wrap gap-2 mt-2">
                ${commonPlatforms.map(site => `<span class="tag-badge compare-tag">${site}</span>`).join('')}
              </div>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  } else {
    html += `
      <div class="mt-6 border-t border-white/5 pt-6 text-center py-8 text-secondary">
        <div class="text-3xl mb-2">🤷</div>
        <div class="text-sm">Aucun point de recoupement évident détecté</div>
        <div class="text-xs text-dim mt-1">Les cibles ne partagent aucun prénom, localisation, email ou plateforme.</div>
      </div>
    `;
  }

  html += '</div>';
  container.innerHTML = html;
  container.classList.remove('hidden');
}

// ── Print date logic ───────────────────────────────────────────────────────
window.addEventListener('beforeprint', () => {
  const dateEl = document.getElementById('print-date');
  if (dateEl) dateEl.textContent = new Date().toLocaleString();
});

document.addEventListener('DOMContentLoaded', init);
window.pivotOnEmail = pivotOnEmail;
window.exportAccounts = exportAccounts;
window.deleteScan = deleteScan;
window.viewHistoryScan = viewHistoryScan;
window.saveScanMetadata = saveScanMetadata;
window.runComparison = runComparison;
