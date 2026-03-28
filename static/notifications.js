// ============================================
// CostShot Notifications — notifications.js
// Place this file in /static/notifications.js
// ============================================

const CS_ALERTS_KEY = 'costshot_price_alerts';
const CS_CHECK_KEY  = 'costshot_last_check';
const CHECK_INTERVAL = 30 * 60 * 1000; // 30 minutes

// ── Register service worker ──
async function registerSW() {
  if (!('serviceWorker' in navigator)) return null;
  try {
    const reg = await navigator.serviceWorker.register('/static/sw.js', { scope: '/' });
    console.log('CostShot SW registered');
    return reg;
  } catch (err) {
    console.error('SW registration failed:', err);
    return null;
  }
}

// ── Request notification permission ──
async function requestPermission() {
  if (!('Notification' in window)) {
    showToast('Your browser does not support notifications.', 'error');
    return false;
  }

  if (Notification.permission === 'granted') return true;

  if (Notification.permission === 'denied') {
    showToast('Notifications blocked. Please enable in browser settings.', 'error');
    return false;
  }

  const permission = await Notification.requestPermission();
  return permission === 'granted';
}

// ── Save a price alert ──
function saveAlert(title, targetPrice, currentPrice, link) {
  const alerts = getAlerts();
  const id = Date.now().toString();

  // Avoid duplicates
  const exists = alerts.find(a => a.title.toLowerCase() === title.toLowerCase());
  if (exists) {
    exists.target_price = targetPrice;
    exists.current_price = currentPrice;
    exists.link = link;
    localStorage.setItem(CS_ALERTS_KEY, JSON.stringify(alerts));
    showToast(`Alert updated for ${title}!`, 'success');
    updateBellBadge();
    return;
  }

  alerts.push({ id, title, target_price: targetPrice, current_price: currentPrice, link, created: Date.now() });
  localStorage.setItem(CS_ALERTS_KEY, JSON.stringify(alerts));
  showToast(`🔔 Alert set! We'll notify you when ${title} drops to ₹${targetPrice}`, 'success');
  updateBellBadge();
}

// ── Get all alerts ──
function getAlerts() {
  try {
    return JSON.parse(localStorage.getItem(CS_ALERTS_KEY) || '[]');
  } catch {
    return [];
  }
}

// ── Remove an alert ──
function removeAlert(id) {
  const alerts = getAlerts().filter(a => a.id !== id);
  localStorage.setItem(CS_ALERTS_KEY, JSON.stringify(alerts));
  updateBellBadge();
  renderAlertsPanel();
}

// ── Clear all alerts ──
function clearAllAlerts() {
  localStorage.removeItem(CS_ALERTS_KEY);
  updateBellBadge();
  renderAlertsPanel();
}

// ── Update bell badge count ──
function updateBellBadge() {
  const count = getAlerts().length;
  const badge = document.getElementById('bell-badge');
  if (!badge) return;
  badge.textContent = count;
  badge.style.display = count > 0 ? 'flex' : 'none';
}

// ── Trigger background price check via SW ──
async function triggerPriceCheck() {
  const lastCheck = parseInt(localStorage.getItem(CS_CHECK_KEY) || '0');
  if (Date.now() - lastCheck < CHECK_INTERVAL) return;

  const alerts = getAlerts();
  if (alerts.length === 0) return;

  const reg = await navigator.serviceWorker?.ready;
  if (reg && reg.active) {
    reg.active.postMessage({ type: 'CHECK_PRICES', alerts });
    localStorage.setItem(CS_CHECK_KEY, Date.now().toString());
  }
}

// ── Show alert set modal ──
function openAlertModal(title, currentPrice, link) {
  const modal = document.getElementById('alert-modal');
  const titleEl = document.getElementById('modal-product-title');
  const priceEl = document.getElementById('modal-current-price');
  const inputEl = document.getElementById('modal-target-price');

  if (!modal) return;

  titleEl.textContent = title;
  priceEl.textContent = `₹${Number(currentPrice).toLocaleString('en-IN')}`;
  inputEl.value = Math.floor(currentPrice * 0.9); // suggest 10% below
  inputEl.max = currentPrice;

  modal.dataset.title = title;
  modal.dataset.currentPrice = currentPrice;
  modal.dataset.link = link;
  modal.classList.remove('hidden');
  modal.classList.add('flex');

  setTimeout(() => {
    document.getElementById('modal-inner')?.classList.remove('scale-95', 'opacity-0');
    document.getElementById('modal-inner')?.classList.add('scale-100', 'opacity-100');
  }, 10);
}

// ── Close modal ──
function closeAlertModal() {
  const modal = document.getElementById('alert-modal');
  const inner = document.getElementById('modal-inner');
  inner?.classList.add('scale-95', 'opacity-0');
  inner?.classList.remove('scale-100', 'opacity-100');
  setTimeout(() => {
    modal?.classList.add('hidden');
    modal?.classList.remove('flex');
  }, 200);
}

// ── Confirm alert from modal ──
async function confirmAlert() {
  const modal = document.getElementById('alert-modal');
  const targetPrice = parseFloat(document.getElementById('modal-target-price').value);
  const title = modal.dataset.title;
  const currentPrice = parseFloat(modal.dataset.currentPrice);
  const link = modal.dataset.link;

  if (!targetPrice || targetPrice <= 0) {
    showToast('Please enter a valid target price.', 'error');
    return;
  }

  if (targetPrice >= currentPrice) {
    showToast('Target price must be lower than current price!', 'error');
    return;
  }

  const granted = await requestPermission();
  if (!granted) return;

  saveAlert(title, targetPrice, currentPrice, link);
  closeAlertModal();
}

// ── Toggle alerts panel ──
function toggleAlertsPanel() {
  const panel = document.getElementById('alerts-panel');
  if (!panel) return;
  if (panel.classList.contains('hidden')) {
    renderAlertsPanel();
    panel.classList.remove('hidden');
    panel.classList.add('flex');
  } else {
    panel.classList.add('hidden');
    panel.classList.remove('flex');
  }
}

// ── Render alerts inside panel ──
function renderAlertsPanel() {
  const container = document.getElementById('alerts-list');
  if (!container) return;
  const alerts = getAlerts();

  if (alerts.length === 0) {
    container.innerHTML = `
      <div class="text-center py-8">
        <div class="text-4xl mb-3">🔔</div>
        <div class="text-gray-500 text-sm">No price alerts set yet.</div>
        <div class="text-gray-400 text-xs mt-1">Click the bell icon on any product card to set an alert.</div>
      </div>`;
    return;
  }

  container.innerHTML = alerts.map(a => `
    <div class="flex items-center justify-between bg-gray-50 rounded-xl px-3 py-3 gap-3">
      <div class="flex-1 min-w-0">
        <div class="font-medium text-gray-800 text-sm truncate">${a.title}</div>
        <div class="text-xs text-gray-500 mt-0.5">
          Alert when ≤ <span class="font-bold text-green-600">₹${a.target_price.toLocaleString('en-IN')}</span>
          <span class="text-gray-400 ml-1">(now ₹${a.current_price.toLocaleString('en-IN')})</span>
        </div>
      </div>
      <button onclick="removeAlert('${a.id}')" class="text-gray-400 hover:text-red-500 transition text-lg flex-shrink-0" title="Remove alert">✕</button>
    </div>
  `).join('');
}

// ── Toast notification ──
function showToast(message, type = 'success') {
  const existing = document.getElementById('cs-toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.id = 'cs-toast';
  toast.className = `fixed bottom-20 left-1/2 -translate-x-1/2 z-[9999] px-5 py-3 rounded-2xl text-white text-sm font-medium shadow-xl transition-all duration-300 flex items-center gap-2 ${
    type === 'success' ? 'bg-green-500' : 'bg-red-500'
  }`;
  toast.innerHTML = `${type === 'success' ? '✅' : '❌'} ${message}`;
  document.body.appendChild(toast);

  setTimeout(() => { toast.style.opacity = '0'; toast.style.transform = 'translateX(-50%) translateY(10px)'; }, 3000);
  setTimeout(() => toast.remove(), 3400);
}

// ── Init on page load ──
document.addEventListener('DOMContentLoaded', async () => {
  await registerSW();
  updateBellBadge();
  triggerPriceCheck();

  // Close modal on backdrop click
  document.getElementById('alert-modal')?.addEventListener('click', (e) => {
    if (e.target === document.getElementById('alert-modal')) closeAlertModal();
  });

  // Close panel on outside click
  document.addEventListener('click', (e) => {
    const panel = document.getElementById('alerts-panel');
    const bell  = document.getElementById('bell-btn');
    if (panel && !panel.contains(e.target) && !bell?.contains(e.target)) {
      panel.classList.add('hidden');
      panel.classList.remove('flex');
    }
  });
});