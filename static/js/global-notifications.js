/**
 * global-notifications.js — Фоновый опрос новых сообщений (legacy)
 * Работает только если Long Polling не активен.
 */
(function() {
  'use strict';

  if (window._globalNotificationsLoaded) return;
  window._globalNotificationsLoaded = true;

  // ✅ Если Long Polling уже используется – не запускаем legacy polling
  if (window.longPollingClient && window.longPollingClient.isRunning) {
    console.log('[global-notifications] Long Polling active, skipping legacy polling');
    return;
  }

  const POLL_INTERVAL = 5000;
  let lastTimestamp = Date.now() / 1000;
  let pollTimer = null;
  let stopped = false;

  async function pollNewMessages() {
    if (stopped) return;

    try {
      const res = await fetch(`/check_new_messages?since=${lastTimestamp}`, {
        cache: 'no-store'
      });

      if (!res.ok) {
        if (res.status === 401) {
          stopPolling();
          return;
        }
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
      const messages = data.messages || [];

      if (messages.length > 0) {
        const maxTs = Math.max(...messages.map(m => m.timestamp));
        if (maxTs > lastTimestamp) {
          lastTimestamp = maxTs;
        }

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

    if (!stopped) {
      pollTimer = setTimeout(pollNewMessages, POLL_INTERVAL);
    }
  }

  function startPolling() {
    if (window.NotificationManager) {
      window.NotificationManager.init();
    }
    pollTimer = setTimeout(pollNewMessages, 1000);
  }

  function stopPolling() {
    stopped = true;
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startPolling);
  } else {
    startPolling();
  }

  window.addEventListener('beforeunload', stopPolling);
})();