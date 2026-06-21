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
  ['view-home', 'view-scanning', 'view-results', 'view-history'].forEach(id => {
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
    holehe:       { icon: '🔑', label: 'Holehe',       desc: 'Vérification email 120+ services' },
    ghunt:        { icon: '🌐', label: 'GHunt',        desc: 'Intelligence Google/Gmail' },
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
}

function renderProfileTab(summary) {
  const container = document.getElementById('tab-profile');
  if (!container) return;

  const confidence = Math.round((summary.confidence_score || 0) * 100);
  const circumference = 2 * Math.PI * 44;
  const offset = circumference - (confidence / 100) * circumference;

  // Top identity card
  const topName = Object.entries(summary.firstnames || {}).sort((a,b) => b[1]-a[1])[0];
  const topLoc  = Object.entries(summary.locations || {}).sort((a,b) => b[1]-a[1])[0];

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

  // Check auth state
  checkAuth();
}

document.addEventListener('DOMContentLoaded', init);
window.pivotOnEmail = pivotOnEmail;
window.exportAccounts = exportAccounts;
window.deleteScan = deleteScan;
window.viewHistoryScan = viewHistoryScan;
