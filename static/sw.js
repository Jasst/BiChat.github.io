self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('push', event => {
  let data = { title: 'New message', body: '', url: '/' };
  if (event.data) {
    try {
      data = event.data.json();
    } catch(e) {}
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
      data: { url: data.url }
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = event.notification.data?.url || '/';
  event.waitUntil(clients.openWindow(url));
});