// Paxen service worker: shows commute alerts pushed by the server (backend/paxen/webpush.py).
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let msg = { title: 'Paxen', body: '', data: {} }
  try {
    msg = { ...msg, ...event.data.json() }
  } catch {
    if (event.data) msg.body = event.data.text()
  }
  event.waitUntil(
    self.registration.showNotification(msg.title, {
      body: msg.body,
      data: msg.data,
      icon: '/icons/192',
      badge: '/icons/192',
      tag: msg.data && msg.data.alert_id ? `alert-${msg.data.alert_id}` : undefined,
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if ('focus' in w) {
          w.navigate(url)
          return w.focus()
        }
      }
      return self.clients.openWindow(url)
    }),
  )
})
