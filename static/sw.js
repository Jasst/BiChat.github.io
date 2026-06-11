// sw.js — Service Worker для push-уведомлений
// ИСПРАВЛЕНИЯ v3:
// 1. activate + clients.claim() — SW берёт контроль немедленно
// 2. notificationclick — фокусируем открытую вкладку вместо новой (iOS/Android)
// 3. push: убраны опции несовместимые с iOS (actions, requireInteraction)
// 4. iOS Safari не поддерживает vibrate, actions, image в уведомлениях — убраны

self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});

self.addEventListener('push', event => {
  let data = { title: 'BiChat', body: 'Новое сообщение', url: '/chat' };

  if (event.data) {
    try {
      data = { ...data, ...event.data.json() };
    } catch(e) {
      data.body = event.data.text() || '';
    }
  }

  if (!data.url || typeof data.url !== 'string') data.url = '/chat';

  // ИСПРАВЛЕНИЕ: минимальный набор опций совместимых с iOS Safari 16.4+
  // iOS не поддерживает: actions, image, vibrate (игнорирует, но иногда ломает)
  // requireInteraction: убран — на iOS уведомление не показывается вообще если он есть
  const options = {
    body: data.body,
    icon: '/static/icon-192.png',
   
    data: { url: data.url },
    tag: data.tag || 'bichat-msg',
    renotify: true,

    // vibrate: убрано — iOS игнорирует, Android PWA поддерживает но не критично
    // actions: убраны — iOS не поддерживает
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = event.notification.data?.url || '/chat';

  // ИСПРАВЛЕНИЕ 3: сначала ищем уже открытую вкладку с нашим origin
  // и фокусируем её, вместо открытия новой — это ключевой фикс для iOS и Android
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      // Ищем вкладку с нашим origin
      for (const client of windowClients) {
        const clientUrl = new URL(client.url);
        const targetUrl = new URL(url, self.location.origin);

        if (clientUrl.origin === self.location.origin) {
          // Вкладка нашего сайта уже открыта — фокусируем и навигируем
          return client.focus().then(focused => {
            if (focused.navigate) {
              return focused.navigate(url);
            }
            // navigate не всегда доступен (Safari) — постим сообщение
            focused.postMessage({ type: 'navigate', url });
            return focused;
          });
        }
      }
      // Открытой вкладки нет — открываем новую
      return clients.openWindow(url);
    })
  );
});

self.addEventListener('pushsubscriptionchange', function(event) {
    console.log('Push subscription change event (iOS)');
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
            for (const client of clients) {
                client.postMessage({ type: 'pushsubscriptionchange' });
            }
        })
    );
});