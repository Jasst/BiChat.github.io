self.addEventListener('install', event => {
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(clients.claim());
});

self.addEventListener('push', event => {
    let data = {
        type: 'message',
        title: 'BiChat',
        body: 'New message',
        url: '/chat'
    };

    if (event.data) {
        try {
            const parsed = event.data.json();
            data = { ...data, ...parsed };
        } catch (e) {
            data.body = event.data.text() || '';
        }
    }

    const isCall = data.type === 'incoming_call';
    const tag = isCall ? `call-${data.call_id}` : 'bichat-msg';

    const options = {
        body: data.body,
        icon: '/static/icon-192.png',
        badge: '/static/badge-72.png',
        data: {
            url: data.url,
            type: data.type,
            call_id: data.call_id || null,
            from: data.from || null,
            from_name: data.from_name || null
        },
        tag: tag,
        renotify: true,
        vibrate: isCall ? [200, 100, 200] : undefined,
        silent: false
    };

    event.waitUntil(
        self.registration.showNotification(
            isCall ? `📞 ${data.from_name || 'Incoming call'}` : data.title,
            options
        )
    );
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    const data = event.notification.data || {};
    const url = data.url || '/chat';
    const type = data.type;
    const callId = data.call_id;

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
            for (const client of windowClients) {
                if (client.url.startsWith(self.location.origin)) {
                    client.focus();
                    // Отправляем сообщение в приложение
                    client.postMessage({
                        type: type === 'incoming_call' ? 'open_call' : 'navigate',
                        url: url,
                        call_id: callId,
                        from: data.from,
                        from_name: data.from_name
                    });
                    return;
                }
            }
            return clients.openWindow(url);
        })
    );
});

self.addEventListener('pushsubscriptionchange', event => {
    console.log('Push subscription expired/changed');
    event.waitUntil(
        clients.matchAll({ type: 'window' }).then(clientsArr => {
            for (const client of clientsArr) {
                client.postMessage({ type: 'pushsubscriptionchange' });
            }
        })
    );
});