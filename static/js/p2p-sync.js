/**
 * p2p-sync.js — P2P-синхронизация с fallback на Long Polling
 * 
 * 🔔 ВАЖНО: Этот модуль НЕ обрабатывает уведомления.
 * Уведомления обрабатываются в chat.html через appendMessageToUI.
 */
class P2PSync {
  constructor() {
    this.subscriptions = new Map();
    this.pollIntervals = new Map();
    this.lastSync = new Map();
  }

  subscribe(chatId, onMessage) {
    const room = window.GunConfig.getRoom(chatId);
    const key = `sub_${chatId}`;

    // Подписка на Gun (если подключился)
    if (window.GunConfig.gun) {
      if (this.subscriptions.has(key)) {
        this.subscriptions.get(key).off();
      }

      const listener = room.map().on((data, senderAddr) => {
        if (senderAddr === window.GunConfig.userId) return;
        try {
          const payload = typeof data === 'string' ? JSON.parse(data) : data;
          onMessage({
            sender: senderAddr,
            encryptedPayload: payload,
            timestamp: payload.ts || Date.now(),
            tx_id: payload.tx_id,
            via: 'gun'
          });
          // 🔔 Уведомления обрабатываются ВНЕ этого модуля (в chat.html)
        } catch (e) {
          console.warn('⚠️ P2P parse error:', e);
        }
      });
      this.subscriptions.set(key, listener);
    }

    // 🔥 Fallback: Long Polling
    this._startPolling(chatId, onMessage);

    return () => {
      if (this.subscriptions.has(key)) {
        this.subscriptions.get(key).off();
        this.subscriptions.delete(key);
      }
      this._stopPolling(chatId);
    };
  }

  _startPolling(chatId, onMessage) {
    if (this.pollIntervals.has(chatId)) return;
    this.lastSync.set(chatId, 0);

    let retryCount = 0;
    const MAX_RETRY = 5;
    const BASE_INTERVAL = 2000;

    const poll = async () => {
      try {
        const since = this.lastSync.get(chatId) || 0;
        const res = await fetch(`/p2p-poll?chat=${encodeURIComponent(chatId)}&since=${since}`);

        if (res.ok) {
          retryCount = 0;
          const messages = await res.json();

          if (messages.length > 0) {
            messages.forEach(msg => {
              if (msg.ts > (this.lastSync.get(chatId) || 0)) {
                this.lastSync.set(chatId, msg.ts);
              }
              onMessage({
                sender: msg.sender,
                encryptedPayload: {
                  content: msg.content,
                  image: msg.image,
                  version: 'hybrid-v2',
                  tx_id: msg.tx_id
                },
                timestamp: msg.ts > 1e10 ? msg.ts : msg.ts * 1000,
                tx_id: msg.tx_id,
                via: 'poll'
              });
              // 🔔 Уведомления обрабатываются ВНЕ этого модуля (в chat.html)
            });
          }
        }
      } catch (e) {
        retryCount = Math.min(retryCount + 1, MAX_RETRY);
        console.debug(`ℹ️ P2P poll error (retry ${retryCount}/${MAX_RETRY}):`, e.message);
      }

      if (this.pollIntervals.has(chatId)) {
        const nextDelay = BASE_INTERVAL * Math.pow(1.5, retryCount);
        setTimeout(poll, nextDelay);
      }
    };

    poll();
    this.pollIntervals.set(chatId, { active: true });
    console.debug(`🔄 Started long polling for: ${chatId.substring(0,20)}...`);
  }

  _stopPolling(chatId) {
    const entry = this.pollIntervals.get(chatId);
    if (entry) {
      if (entry.active) entry.active = false;
      this.pollIntervals.delete(chatId);
      this.lastSync.delete(chatId);
      console.debug(`🛑 Stopped long polling for: ${chatId.substring(0,20)}...`);
    }
  }

  async send(chatId, encryptedPayload, txId) {
    if (window.GunConfig.gun) {
      const room = window.GunConfig.getRoom(chatId);
      const packet = {
        ...encryptedPayload,
        ts: Date.now(),
        tx_id: txId,
        sender_addr: window.GunConfig.userId
      };
      room.get(window.GunConfig.userId).put(packet);
    }
    return { via: 'hybrid', delivered: true };
  }

  unsubscribeAll() {
    for (const [, listener] of this.subscriptions) {
      if (typeof listener.off === 'function') listener.off();
    }
    this.subscriptions.clear();
    for (const [chatId] of this.pollIntervals) {
      this._stopPolling(chatId);
    }
    this.pollIntervals.clear();
  }
}

window.P2PSync = P2PSync;

