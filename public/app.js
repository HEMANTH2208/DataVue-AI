/**
 * DataMind AI Frontend Application
 * Handles SSE streaming, Plotly chart rendering, Mermaid ER diagrams,
 * SQL transparency panel, tool trace badges, and multi-turn conversation.
 */

/* ============================================================
   CONFIGURATION
   ============================================================ */
const API_BASE = window.location.origin;

/* ============================================================
   STATE
   ============================================================ */
let sessionId = null;
let isLoading = false;
let sidebarCollapsed = false;
let currentSchemaData = null;

/* ============================================================
   DOM REFERENCES
   ============================================================ */
const chatContainer   = document.getElementById('chatContainer');
const chatInput       = document.getElementById('chatInput');
const sendBtn         = document.getElementById('sendBtn');
const welcomeState    = document.getElementById('welcomeState');
const schemaTree      = document.getElementById('schemaTree');
const schemaRefresh   = document.getElementById('schemaRefresh');
const schemaSearch    = document.getElementById('schemaSearch');
const sidebarEl       = document.getElementById('sidebar');
const sidebarToggle   = document.getElementById('sidebarToggle');
const sidebarOpenBtn  = document.getElementById('sidebarOpenBtn');
const clearChatBtn    = document.getElementById('clearChatBtn');
const providerLabel   = document.getElementById('providerLabel');
const sessionIdLabel  = document.getElementById('sessionIdLabel');
const modelSelect     = document.getElementById('modelSelect');
const voiceBtn        = document.getElementById('voiceBtn');
const voiceLangSelect = document.getElementById('voiceLangSelect');

/* ============================================================
   MERMAID INIT
   ============================================================ */
mermaid.initialize({
  startOnLoad: false,
  theme: 'neutral',
  themeVariables: {
    background: '#ffffff',
    primaryColor: '#4f46e5',
    primaryTextColor: '#0f172a',
    lineColor: '#64748b',
    secondaryColor: '#7c3aed',
    tertiaryColor: '#f8fafc',
  },
  er: { layoutDirection: 'TB' },
});

/* ============================================================
   HEALTH CHECK & PROVIDER DISPLAY
   ============================================================ */
async function checkHealth(model = null) {
  try {
    const url = new URL(`${API_BASE}/api/health`);
    if (model) url.searchParams.set('model', model);
    const res = await fetch(url.toString());
    const data = await res.json();
    providerLabel.textContent = data.llm_provider.toUpperCase();
    document.querySelector('.provider-dot').style.background = '#22c55e'; // Green when healthy
  } catch {
    providerLabel.textContent = 'OFFLINE';
    document.querySelector('.provider-dot').style.background = '#ef4444';
  }
}

/* ============================================================
   SCHEMA BROWSER WITH FILTERING
   ============================================================ */
async function loadSchema() {
  schemaTree.innerHTML = '<div class="schema-loading">Loading schema...</div>';
  schemaRefresh.classList.add('spinning');
  try {
    const url = new URL(`${API_BASE}/api/schema`);
    if (sessionId) url.searchParams.set('session_id', sessionId);
    const res = await fetch(url.toString());
    const data = await res.json();
    currentSchemaData = data.schema;
    if (schemaSearch) schemaSearch.value = ''; // Reset search on fresh load
    renderSchema(currentSchemaData);
  } catch {
    schemaTree.innerHTML = '<div class="schema-loading">Failed to load schema.</div>';
  } finally {
    schemaRefresh.classList.remove('spinning');
  }
}

function renderSchema(schema) {
  schemaTree.innerHTML = '';
  const entries = Object.entries(schema || {});
  if (entries.length === 0) {
    schemaTree.innerHTML = '<div class="schema-loading">No matching tables or columns found.</div>';
    return;
  }

  for (const [tableName, tableInfo] of entries) {
    const item = document.createElement('div');
    item.className = 'schema-table-item';

    const nameRow = document.createElement('div');
    nameRow.className = 'schema-table-name';
    const isOpen = !!tableInfo._forceOpen;
    nameRow.innerHTML = `
      <span class="table-icon">${isOpen ? '▼' : '▶'}</span>
      <span>${tableName}</span>
      <span class="table-row-count">${tableInfo.row_count?.toLocaleString() ?? ''}</span>
    `;

    const colsList = document.createElement('div');
    colsList.className = 'schema-columns-list';
    if (isOpen) {
      colsList.classList.add('open');
    }

    for (const col of (tableInfo.columns || [])) {
      const colItem = document.createElement('div');
      colItem.className = 'schema-column-item';
      colItem.innerHTML = `
        <span class="${col.is_primary_key ? 'schema-column-pk' : ''}">${col.is_primary_key ? '🔑' : '·'} ${col.name}</span>
        <span class="schema-column-type">${col.type}</span>
      `;
      colsList.appendChild(colItem);
    }

    nameRow.addEventListener('click', () => {
      const open = colsList.classList.toggle('open');
      nameRow.querySelector('.table-icon').textContent = open ? '▼' : '▶';
    });

    item.appendChild(nameRow);
    item.appendChild(colsList);
    schemaTree.appendChild(item);
  }
}

function filterSchema(query) {
  if (!currentSchemaData) return;
  if (!query) {
    renderSchema(currentSchemaData);
    return;
  }

  const filteredSchema = {};
  for (const [tableName, tableInfo] of Object.entries(currentSchemaData)) {
    const tableMatch = tableName.toLowerCase().includes(query);
    const matchingCols = (tableInfo.columns || []).filter(col => 
      col.name.toLowerCase().includes(query) || col.type.toLowerCase().includes(query)
    );

    if (tableMatch || matchingCols.length > 0) {
      filteredSchema[tableName] = {
        ...tableInfo,
        columns: tableMatch ? tableInfo.columns : matchingCols,
        _forceOpen: true
      };
    }
  }

  renderSchema(filteredSchema);
}

/* ============================================================
   CHAT UI HELPERS
   ============================================================ */
function hideWelcome() {
  if (welcomeState) {
    welcomeState.style.display = 'none';
  }
}

function scrollToBottom(smooth = true) {
  chatContainer.scrollTo({
    top: chatContainer.scrollHeight,
    behavior: smooth ? 'smooth' : 'instant',
  });
}

function addUserMessage(text) {
  hideWelcome();
  const tmpl = document.getElementById('userMsgTemplate').content.cloneNode(true);
  tmpl.querySelector('.message-text').textContent = text;
  chatContainer.appendChild(tmpl);
  scrollToBottom();
}

function addThinkingIndicator() {
  const tmpl = document.getElementById('thinkingTemplate').content.cloneNode(true);
  chatContainer.appendChild(tmpl);
  scrollToBottom();
  return document.getElementById('thinkingMsg');
}

function removeThinkingIndicator() {
  const el = document.getElementById('thinkingMsg');
  if (el) el.remove();
}

/**
 * Creates an empty assistant message frame and returns handles to its panels.
 */
function createAssistantMessage() {
  const tmpl = document.getElementById('assistantMsgTemplate').content.cloneNode(true);
  const wrapper = document.createElement('div');
  wrapper.appendChild(tmpl);
  // The actual message element is the first child
  const msgEl = wrapper.firstElementChild;
  chatContainer.appendChild(msgEl);

  return {
    msgEl,
    traceRow:     msgEl.querySelector('.tool-trace-row'),
    sqlPanel:     msgEl.querySelector('.sql-panel'),
    sqlCode:      msgEl.querySelector('.sql-code'),
    copySqlBtn:   msgEl.querySelector('.copy-sql-btn'),
    chartPanel:   msgEl.querySelector('.chart-panel'),
    chartCont:    msgEl.querySelector('.chart-container'),
    diagramPanel: msgEl.querySelector('.diagram-panel'),
    diagramCont:  msgEl.querySelector('.diagram-container'),
    answerText:   msgEl.querySelector('.answer-text'),
    insightsPanel:msgEl.querySelector('.insights-panel'),
    insightsCont: msgEl.querySelector('.insights-content'),
  };
}

/* ---- Tool trace badge helpers ---- */
const TOOL_ICONS = {
  get_schema:       '🗄️',
  execute_query:    '⚡',
  generate_chart:   '📊',
  generate_flowchart:'🗂️',
  explain_data:     '💡',
};

function addToolBadge(traceRow, toolName) {
  const badge = document.createElement('span');
  badge.className = 'tool-badge tool-badge-pending';
  badge.dataset.toolBadge = toolName;
  badge.innerHTML = `
    <span class="tool-badge-spinner"></span>
    ${TOOL_ICONS[toolName] || '🔧'} ${toolName}
  `;
  traceRow.appendChild(badge);
  return badge;
}

function completeBadge(badge, success, ms) {
  badge.className = `tool-badge ${success ? 'tool-badge-success' : 'tool-badge-error'}`;
  const icon = TOOL_ICONS[badge.dataset.toolBadge] || '🔧';
  badge.innerHTML = `${success ? '✓' : '✗'} ${icon} ${badge.dataset.toolBadge}${ms ? ` <small>(${ms}ms)</small>` : ''}`;
}

/* ============================================================
   CHART RENDERING (Plotly)
   ============================================================ */
function renderChart(container, chartData) {
  if (!chartData) return;
  const spec = chartData.plotly_spec;
  if (!spec || !spec.data) return;

  const layout = Object.assign({
    margin: { t: 50, r: 20, b: 60, l: 60 },
    font: { family: "'Inter', sans-serif", color: '#334155', size: 12 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    colorway: ['#4f46e5', '#7c3aed', '#06b6d4', '#10b981', '#f59e0b', '#ef4444'],
    xaxis: { gridcolor: 'rgba(0,0,0,0.06)', zerolinecolor: 'rgba(0,0,0,0.1)', tickfont: { color: '#64748b' } },
    yaxis: { gridcolor: 'rgba(0,0,0,0.06)', zerolinecolor: 'rgba(0,0,0,0.1)', tickfont: { color: '#64748b' } },
  }, spec.layout || {});
  
  // Strip any server-side dark theme layouts
  if (layout.template) {
    delete layout.template;
  }

  Plotly.newPlot(container, spec.data, layout, {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  });
}

/* ============================================================
   DIAGRAM RENDERING (Mermaid)
   ============================================================ */
let diagramCounter = 0;

async function renderDiagram(container, diagramData) {
  if (!diagramData || !diagramData.mermaid_markup) return;
  const id = `mermaid-diagram-${++diagramCounter}`;
  container.innerHTML = `<div id="${id}">${diagramData.mermaid_markup}</div>`;
  try {
    const { svg } = await mermaid.render(id, diagramData.mermaid_markup);
    container.innerHTML = svg;
  } catch (err) {
    container.innerHTML = `<pre style="color:#f87171;font-size:0.8rem">${diagramData.mermaid_markup}</pre>`;
  }
}

/* ============================================================
   MAIN QUERY — SSE Streaming
   ============================================================ */
async function sendQuery(question) {
  if (isLoading || !question.trim()) return;

  setLoading(true);
  addUserMessage(question);

  const thinkingEl = addThinkingIndicator();
  const thinkingStatus = thinkingEl.querySelector('#thinkingStatus');

  // We'll build the assistant message incrementally
  let msgHandles = null;
  const pendingBadges = {};

  const url = new URL(`${API_BASE}/api/query/stream`);
  url.searchParams.set('question', question);
  if (sessionId) url.searchParams.set('session_id', sessionId);
  if (modelSelect) url.searchParams.set('model', modelSelect.value);

  const evtSource = new EventSource(url.toString());

  evtSource.addEventListener('status', (e) => {
    const data = JSON.parse(e.data);
    if (thinkingStatus) thinkingStatus.textContent = data.message || 'Thinking...';
    if (data.session_id) {
      sessionId = data.session_id;
      sessionIdLabel.textContent = `Session: ${sessionId.slice(0, 8)}…`;
    }
  });

  evtSource.addEventListener('tool_start', (e) => {
    const data = JSON.parse(e.data);
    // Create message frame on first tool
    if (!msgHandles) {
      removeThinkingIndicator();
      msgHandles = createAssistantMessage();
    }
    if (thinkingStatus) thinkingStatus.textContent = `Running ${data.tool}…`;
    const badge = addToolBadge(msgHandles.traceRow, data.tool);
    pendingBadges[data.tool] = badge;
    scrollToBottom();
  });

  evtSource.addEventListener('tool_result', (e) => {
    const data = JSON.parse(e.data);
    const badge = pendingBadges[data.tool];
    if (badge) completeBadge(badge, data.success, data.execution_time_ms);
    scrollToBottom();
  });

  evtSource.addEventListener('sql', (e) => {
    if (!msgHandles) return;
    const data = JSON.parse(e.data);
    if (data.sql) {
      msgHandles.sqlPanel.style.display = 'block';
      msgHandles.sqlCode.textContent = data.sql;
      // Copy button
      msgHandles.copySqlBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(data.sql).then(() => {
          msgHandles.copySqlBtn.textContent = 'Copied!';
          setTimeout(() => { msgHandles.copySqlBtn.textContent = 'Copy'; }, 2000);
        });
      });
    }
    scrollToBottom();
  });

  evtSource.addEventListener('chart', (e) => {
    if (!msgHandles) return;
    const data = JSON.parse(e.data);
    msgHandles.chartPanel.style.display = 'block';
    // Delay slightly so panel is in DOM before Plotly measures it
    setTimeout(() => renderChart(msgHandles.chartCont, data), 80);
    scrollToBottom();
  });

  evtSource.addEventListener('diagram', (e) => {
    if (!msgHandles) return;
    const data = JSON.parse(e.data);
    msgHandles.diagramPanel.style.display = 'block';
    renderDiagram(msgHandles.diagramCont, data);
    scrollToBottom();
  });

  evtSource.addEventListener('insights', (e) => {
    if (!msgHandles) return;
    const data = JSON.parse(e.data);
    msgHandles.insightsPanel.style.display = 'block';
    msgHandles.insightsCont.innerHTML = formatMarkdown(data.explanation || '');
    scrollToBottom();
  });

  evtSource.addEventListener('answer', (e) => {
    removeThinkingIndicator();
    if (!msgHandles) {
      msgHandles = createAssistantMessage();
    }
    const data = JSON.parse(e.data);
    msgHandles.answerText.innerHTML = formatMarkdown(data.content || '');
    scrollToBottom();
  });

  evtSource.addEventListener('answer_chunk', (e) => {
    removeThinkingIndicator();
    if (!msgHandles) {
      msgHandles = createAssistantMessage();
    }
    const data = JSON.parse(e.data);
    msgHandles.answerText.innerHTML = formatMarkdown(data.content || '');
    scrollToBottom();
  });

  evtSource.addEventListener('complete', (e) => {
    evtSource.close();
    removeThinkingIndicator();
    setLoading(false);
    scrollToBottom();
  });

  evtSource.onerror = () => {
    evtSource.close();
    removeThinkingIndicator();
    if (!msgHandles) {
      msgHandles = createAssistantMessage();
    }
    msgHandles.answerText.textContent = '⚠️ Connection error. Please try again.';
    msgHandles.answerText.style.color = '#f87171';
    setLoading(false);
    scrollToBottom();
  };
}

function formatMarkdown(text) {
  if (!text) return '';

  let html = text;

  // 1. Force conversion of $ to ₹ for Indian specificity
  html = html.replace(/\$/g, '₹');

  // 2. Convert markdown tables
  const tableRegex = /((?:\|[^\n]+\|\r?\n?)+)/g;
  html = html.replace(tableRegex, (match) => {
    const lines = match.trim().split('\n');
    if (lines.length < 2) return match;

    let tableHtml = '<div class="table-responsive"><table class="markdown-table">';
    let hasHeader = false;
    let headers = [];

    lines.forEach((line) => {
      // Skip separator line like |---|---|
      if (line.trim().match(/^[|\s:-]+$/)) return;

      const cells = line.split('|').map(c => c.trim()).filter((c, i, arr) => i > 0 && i < arr.length - 1);
      if (cells.length === 0) return;

      if (!hasHeader) {
        tableHtml += '<thead><tr>';
        headers = cells.map(cell => cell.replace(/\$/g, '₹'));
        headers.forEach(header => {
          tableHtml += `<th>${header}</th>`;
        });
        tableHtml += '</tr></thead><tbody>';
        hasHeader = true;
      } else {
        tableHtml += '<tr>';
        cells.forEach((cell, index) => {
          let formattedCell = cell.replace(/\$/g, '₹');
          // If the column header is monetary, format raw numbers to Indian currency ₹
          if (index < headers.length) {
            const h = headers[index].toLowerCase();
            const isMonetary = h.includes('price') || h.includes('revenue') || h.includes('sales') || h.includes('amount') || h.includes('total') || h.includes('value') || h.includes('cost') || h.includes('₹');
            if (isMonetary) {
              const cleanedVal = cell.replace(/[₹$,]/g, '').trim();
              const num = parseFloat(cleanedVal);
              if (!isNaN(num)) {
                formattedCell = '₹' + num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
              }
            }
          }
          tableHtml += `<td>${formattedCell}</td>`;
        });
        tableHtml += '</tr>';
      }
    });

    if (hasHeader) tableHtml += '</tbody>';
    tableHtml += '</table></div>';
    return tableHtml;
  });

  // 3. Convert headers
  html = html.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.*?)$/gm, '<h1>$1</h1>');

  // 4. Convert bold text
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

  // 5. Convert lists
  html = html.replace(/^\s*[\*\-]\s+(.*?)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*?<\/li>)+/gs, (match) => {
    return `<ul class="markdown-list">${match}</ul>`;
  });

  // 6. Line breaks (preserve tag tags and lists)
  html = html.replace(/(?<!>)\n(?!<)/g, '<br/>');

  return html;
}

/* ============================================================
   LOADING STATE
   ============================================================ */
function setLoading(loading) {
  isLoading = loading;
  sendBtn.disabled = loading;
  chatInput.disabled = loading;
}

/* ============================================================
   AUTO-RESIZE TEXTAREA
   ============================================================ */
chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 180) + 'px';
});

/* ============================================================
   SEND ON ENTER (Shift+Enter = newline)
   ============================================================ */
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const val = chatInput.value.trim();
    if (val) {
      chatInput.value = '';
      chatInput.style.height = 'auto';
      sendQuery(val);
    }
  }
});

sendBtn.addEventListener('click', () => {
  const val = chatInput.value.trim();
  if (val) {
    chatInput.value = '';
    chatInput.style.height = 'auto';
    sendQuery(val);
  }
});

/* ============================================================
   SUGGESTION CHIPS
   ============================================================ */
function setupChips() {
  document.querySelectorAll('.suggestion-chip, .welcome-chip').forEach((btn) => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.query;
      if (q) sendQuery(q);
    });
  });
}

/* ============================================================
   SIDEBAR TOGGLE
   ============================================================ */
sidebarToggle.addEventListener('click', () => {
  sidebarCollapsed = !sidebarCollapsed;
  sidebarEl.classList.toggle('collapsed', sidebarCollapsed);
  sidebarToggle.textContent = sidebarCollapsed ? '›' : '‹';
  if (sidebarOpenBtn) sidebarOpenBtn.style.display = sidebarCollapsed ? 'flex' : 'none';
});

if (sidebarOpenBtn) {
  sidebarOpenBtn.addEventListener('click', () => {
    sidebarCollapsed = false;
    sidebarEl.classList.remove('collapsed');
    sidebarToggle.textContent = '‹';
    sidebarOpenBtn.style.display = 'none';
  });
}

/* ============================================================
   SCHEMA REFRESH BUTTON & SEARCH FILTER
   ============================================================ */
schemaRefresh.addEventListener('click', loadSchema);

if (schemaSearch) {
  schemaSearch.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase().trim();
    filterSchema(q);
  });
}

/* ============================================================
   CLEAR CHAT
   ============================================================ */
clearChatBtn.addEventListener('click', () => {
  // Remove all messages
  Array.from(chatContainer.children).forEach(el => {
    if (el !== welcomeState) el.remove();
  });
  if (welcomeState) welcomeState.style.display = 'flex';
  sessionId = null;
  sessionIdLabel.textContent = '';
});

/* ============================================================
   SPEECH-TO-TEXT (STT) & VOICE INPUT
   ============================================================ */
let recognition = null;
let isRecording = false;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {
    isRecording = true;
    if (voiceBtn) {
      voiceBtn.classList.add('recording');
      voiceBtn.title = "Stop Voice Recording";
    }
  };

  recognition.onend = () => {
    isRecording = false;
    if (voiceBtn) {
      voiceBtn.classList.remove('recording');
      voiceBtn.title = "Start voice recording";
    }
  };

  recognition.onresult = (event) => {
    const resultText = event.results[0][0].transcript;
    if (chatInput && resultText) {
      const currentVal = chatInput.value.trim();
      chatInput.value = currentVal ? `${currentVal} ${resultText}` : resultText;
      chatInput.dispatchEvent(new Event('input'));
    }
  };

  recognition.onerror = (event) => {
    console.error("Speech Recognition Error:", event.error);
    isRecording = false;
    if (voiceBtn) {
      voiceBtn.classList.remove('recording');
    }
  };
}

if (voiceBtn && recognition) {
  voiceBtn.addEventListener('click', () => {
    if (isRecording) {
      recognition.stop();
    } else {
      recognition.lang = voiceLangSelect ? voiceLangSelect.value : 'en-US';
      recognition.start();
    }
  });
} else if (voiceBtn) {
  voiceBtn.style.display = 'none';
}

if (modelSelect) {
  modelSelect.addEventListener('change', () => {
    checkHealth(modelSelect.value);
  });
}

/* ============================================================
   INIT
   ============================================================ */
async function init() {
  // Initialize unique session ID if not set
  if (!sessionId) {
    sessionId = 'session_' + Math.random().toString(36).substring(2, 15);
    sessionIdLabel.textContent = `Session: ${sessionId.slice(0, 8)}…`;
  }

  const defaultModel = modelSelect ? modelSelect.value : null;
  initDatabaseUploadPanel();
  await checkHealth(defaultModel);
  await loadSchema();
  await updateDatabaseStatusUI();
  setupChips();
  chatInput.focus();
}

init();

/* ============================================================
   DATABASE UPLOAD & SWITCHING LOGIC
   ============================================================ */

async function updateDatabaseStatusUI() {
  if (!sessionId) return;
  try {
    const res = await fetch(`${API_BASE}/api/database/status/${sessionId}`);
    const data = await res.json();
    
    const infoName = document.getElementById('dbInfoName');
    const infoType = document.getElementById('dbInfoType');
    const infoTables = document.getElementById('dbInfoTables');
    const infoStatus = document.getElementById('dbInfoStatus');
    const infoIndicatorDot = document.getElementById('dbInfoIndicatorDot');

    if (infoName) infoName.textContent = data.database_name || 'ecommerce.db';
    if (infoType) infoType.textContent = data.database_type || 'SQLite';
    
    if (data.source_type === 'uploaded') {
      document.getElementById('dbToggleUpload').classList.add('active');
      document.getElementById('dbToggleDefault').classList.remove('active');
      document.getElementById('dbUploadPanel').style.display = 'flex';
      
      // Update table count from current schema data
      if (currentSchemaData) {
        if (infoTables) infoTables.textContent = Object.keys(currentSchemaData).length;
      } else {
        const schemaRes = await fetch(`${API_BASE}/api/database/schema/${sessionId}`);
        const schemaData = await schemaRes.json();
        if (infoTables) infoTables.textContent = Object.keys(schemaData.schema || {}).length;
      }
      
      if (infoStatus) {
        infoStatus.textContent = data.status || 'Ready';
        infoStatus.className = 'status-ready';
      }
      if (infoIndicatorDot) {
        infoIndicatorDot.className = 'db-info-indicator-dot active';
      }
      
      if (providerLabel) {
        providerLabel.textContent = (modelSelect ? modelSelect.value : 'gemini').toUpperCase();
      }
    } else {
      document.getElementById('dbToggleDefault').classList.add('active');
      document.getElementById('dbToggleUpload').classList.remove('active');
      document.getElementById('dbUploadPanel').style.display = 'none';
      
      if (infoTables) infoTables.textContent = '6'; // Default e-commerce DB has 6 tables
      if (infoStatus) {
        infoStatus.textContent = 'Ready';
        infoStatus.className = 'status-ready';
      }
      if (infoIndicatorDot) {
        infoIndicatorDot.className = 'db-info-indicator-dot active';
      }
      
      if (providerLabel) {
        providerLabel.textContent = (modelSelect ? modelSelect.value : 'gemini').toUpperCase();
      }
    }
  } catch (err) {
    console.error('Failed to update DB status UI:', err);
  }
}

async function uploadDatabaseFile(file) {
  if (!sessionId) {
    sessionId = 'session_' + Math.random().toString(36).substring(2, 15);
    sessionIdLabel.textContent = `Session: ${sessionId.slice(0, 8)}…`;
  }

  const uploadStatus = document.getElementById('dbUploadStatus');
  const statusDot = document.getElementById('dbStatusDot');
  const statusMessage = document.getElementById('dbStatusMessage');
  const progressContainer = document.getElementById('dbProgressContainer');
  const progressBar = document.getElementById('dbProgressBar');

  if (uploadStatus) uploadStatus.style.display = 'flex';
  if (statusDot) statusDot.className = 'db-status-dot uploading';
  if (statusMessage) statusMessage.textContent = 'Uploading database...';
  if (progressContainer) progressContainer.style.display = 'block';
  if (progressBar) progressBar.style.width = '0%';

  const formData = new FormData();
  formData.append('file', file);

  const xhr = new XMLHttpRequest();
  
  xhr.upload.addEventListener('progress', (e) => {
    if (e.lengthComputable) {
      const percent = Math.round((e.loaded / e.total) * 100);
      if (progressBar) progressBar.style.width = `${percent}%`;
    }
  });

  xhr.onload = async () => {
    if (xhr.status === 200) {
      const response = JSON.parse(xhr.responseText);
      
      if (statusDot) statusDot.className = 'db-status-dot processing';
      if (statusMessage) statusMessage.textContent = 'Validating and building schema...';
      if (progressContainer) progressContainer.style.display = 'none';

      if (response.session_id) {
        sessionId = response.session_id;
        sessionIdLabel.textContent = `Session: ${sessionId.slice(0, 8)}…`;
      }

      await loadSchema();
      await updateDatabaseStatusUI();
      
      if (statusDot) statusDot.className = 'db-status-dot ready';
      if (statusMessage) statusMessage.textContent = 'Database Connected ✓';
      
      // Invalidate chat logs on database switch to prevent query mixups
      clearChatBtn.click();
    } else {
      let errorMsg = 'Upload failed';
      try {
        const errorData = JSON.parse(xhr.responseText);
        errorMsg = errorData.error || errorMsg;
      } catch {}
      
      if (statusDot) statusDot.className = 'db-status-dot error';
      if (statusMessage) statusMessage.textContent = `Error: ${errorMsg}`;
      if (progressContainer) progressContainer.style.display = 'none';
      
      const infoStatus = document.getElementById('dbInfoStatus');
      if (infoStatus) {
        infoStatus.textContent = 'Upload Error';
        infoStatus.className = 'status-error';
      }
    }
  };

  xhr.onerror = () => {
    if (statusDot) statusDot.className = 'db-status-dot error';
    if (statusMessage) statusMessage.textContent = 'Error: Connection lost.';
    if (progressContainer) progressContainer.style.display = 'none';
  };

  xhr.open('POST', `${API_BASE}/api/database/upload?session_id=${sessionId}`);
  xhr.send(formData);
}

async function switchDatabase(sourceType) {
  if (!sessionId) {
    sessionId = 'session_' + Math.random().toString(36).substring(2, 15);
    sessionIdLabel.textContent = `Session: ${sessionId.slice(0, 8)}…`;
  }

  try {
    const res = await fetch(`${API_BASE}/api/database/select/${sessionId}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ source_type: sourceType }),
    });

    if (res.ok) {
      await loadSchema();
      await updateDatabaseStatusUI();
      // Clear conversation context to prevent mixing queries
      clearChatBtn.click();
    } else {
      const errorData = await res.json();
      alert(`Failed to switch database: ${errorData.error}`);
    }
  } catch (err) {
    console.error('Error switching database:', err);
    alert('Failed to switch database. Please check your connection.');
  }
}

function initDatabaseUploadPanel() {
  const dbToggleDefault = document.getElementById('dbToggleDefault');
  const dbToggleUpload = document.getElementById('dbToggleUpload');
  const dbUploadPanel = document.getElementById('dbUploadPanel');
  const dbDropZone = document.getElementById('dbDropZone');
  const dbFileInput = document.getElementById('dbFileInput');

  if (dbToggleDefault) {
    dbToggleDefault.addEventListener('click', () => {
      if (!dbToggleDefault.classList.contains('active')) {
        switchDatabase('default');
      }
    });
  }

  if (dbToggleUpload) {
    dbToggleUpload.addEventListener('click', () => {
      if (!dbToggleUpload.classList.contains('active')) {
        dbUploadPanel.style.display = 'flex';
        dbToggleUpload.classList.add('active');
        dbToggleDefault.classList.remove('active');
        
        fetch(`${API_BASE}/api/database/status/${sessionId || ''}`)
          .then(res => res.json())
          .then(data => {
            if (data.source_type === 'uploaded' || data.original_uploaded_path) {
              switchDatabase('uploaded');
            }
          }).catch(() => {});
      }
    });
  }

  if (dbDropZone && dbFileInput) {
    dbDropZone.addEventListener('click', () => dbFileInput.click());
    
    dbFileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        uploadDatabaseFile(e.target.files[0]);
      }
    });

    dbDropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dbDropZone.classList.add('dragover');
    });

    dbDropZone.addEventListener('dragleave', () => {
      dbDropZone.classList.remove('dragover');
    });

    dbDropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dbDropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) {
        uploadDatabaseFile(e.dataTransfer.files[0]);
      }
    });
  }
}
