// ============================================
// CostShot Service Worker — sw.js
// Place this file in /static/sw.js
// ============================================

const CACHE_NAME = 'costshot-v1';
const ALERT_CHECK_INTERVAL = 30 * 60 * 1000; // Check every 30 mins

// ── Install ──
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

// ── Activate ──
self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

// ── Handle push notifications from server ──
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || 'CostShot Price Alert 🔔';
  const options = {
    body:    data.body || 'A product price has dropped!',
    icon:    '/static/images/icon-192.png',
    badge:   '/static/images/icon-72.png',
    tag:     data.tag || 'price-alert',
    vibrate: [200, 100, 200],
    data:    { url: data.url || '/' },
    actions: [
      { action: 'view',    title: '🛒 View Deal' },
      { action: 'dismiss', title: '✕ Dismiss'   },
    ]
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// ── Handle notification click ──
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  if (event.action === 'dismiss') return;

  const url = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url === url && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});

// ── Background price check (triggered by main thread) ──
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'CHECK_PRICES') {
    checkPriceAlerts(event.data.alerts);
  }
});

async function checkPriceAlerts(alerts) {
  if (!alerts || alerts.length === 0) return;

  for (const alert of alerts) {
    try {
      // Fetch current price via our endpoint
      const res = await fetch(`/api/price-check?title=${encodeURIComponent(alert.title)}`);
      if (!res.ok) continue;
      const data = await res.json();

      if (data.current_price && data.current_price <= alert.target_price) {
        await self.registration.showNotification('💰 Price Drop Alert — CostShot', {
          body:    `${alert.title} is now ₹${data.current_price} (your target: ₹${alert.target_price})`,
          icon:    '/static/images/cs-icon.png',
          badge:   '/static/images/cs-icon.png',
          tag:     `alert-${alert.id}`,
          vibrate: [200, 100, 200],
          data:    { url: data.link || '/' },
          actions: [
            { action: 'view',    title: '🛒 Buy Now' },
            { action: 'dismiss', title: '✕ Dismiss'  },
          ]
        });
      }
    } catch (err) {
      console.error('Price check failed:', err);
    }
  }
}
