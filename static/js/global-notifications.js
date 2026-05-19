/**
 * global-notifications.js — Фоновый опрос новых сообщений
 * Работает на всех страницах мессенджера.
 */
(function() {
  'use strict';

  if (window._globalNotificationsLoaded) return;
  window._globalNotificationsLoaded = true;

  const POLL_INTERVAL = 5000; // 5 секунд
  let lastTimestamp = Date.now() / 1000; // при старте – текущее время
  let pollTimer = null;
  let stopped = false;

  async function pollNewMessages() {
    if (stopped) return;

    try {
      const res = await fetch(`/check_new_messages?since=${lastTimestamp}`, {
        cache: 'no-store'
      });

      if (!res.ok) {
        // Если пользователь не авторизован, прекращаем
        if (res.status === 401) {
          stopPolling();
          return;
        }
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
      const messages = data.messages || [];

      if (messages.length > 0) {
        // Обновляем метку времени по последнему сообщению
        const maxTs = Math.max(...messages.map(m => m.timestamp));
        if (maxTs > lastTimestamp) {
          lastTimestamp = maxTs;
        }

        // Отправляем каждое сообщение в NotificationManager
        const nm = window.NotificationManager;
        if (nm && typeof nm.handleIncomingMessage === 'function') {
          messages.forEach(msg => {
            nm.handleIncomingMessage({
              sender: msg.sender,
              chatId: msg.chatId,
              content: msg.preview,
              image: null,
              timestamp: msg.timestamp * 1000,
              isGroup: msg.isGroup,
              messageId: msg.id
            });
          });
        }
      }
    } catch (e) {
      console.debug('ℹ️ Polling error:', e.message);
    }

    // Планируем следующий опрос
    if (!stopped) {
      pollTimer = setTimeout(pollNewMessages, POLL_INTERVAL);
    }
  }

  function startPolling() {
    // Ждём инициализации NotificationManager
    if (window.NotificationManager) {
      window.NotificationManager.init();
    }

    // Начинаем опрос с небольшой задержкой, чтобы не блокировать загрузку страницы
    pollTimer = setTimeout(pollNewMessages, 1000);
  }

  function stopPolling() {
    stopped = true;
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  // Запуск при загрузке DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startPolling);
  } else {
    startPolling();
  }

  // Остановка при выгрузке страницы
  window.addEventListener('beforeunload', stopPolling);

})();