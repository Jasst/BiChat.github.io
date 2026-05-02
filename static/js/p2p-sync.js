/**
 * p2p-sync.js — P2P-синхронизация с fallback на Long Polling
 * 
 * 🔔 ВАЖНО: Этот модуль НЕ обрабатывает уведомления.
 * Он только доставляет зашифрованные сообщения.
 * Уведомления обрабатываются в chat.html через NotificationManager.
 */
class P2PSync {
  constructor() {
    this.subscriptions = new Map();
    this.pollIntervals = new Map();
    this.lastSync = new Map();
    this.userId = window.GunConfig?.userId;
  }

  subscribe(chatId, onMessage) {
    if (!chatId || typeof onMessage !== 'function') {
      console.error('❌ P2PSync.subscribe: invalid arguments');
      return () => {};
    }

    const room = window.GunConfig?.getRoom?.(chatId);
    const key = `sub_${chatId}`;
    const self = this;

    let gunUnsub = null;
    if (window.GunConfig?.gun && room) {
      if (this.subscriptions.has(key)) {
        const oldListener = this.subscriptions.get(key);
        if (typeof oldListener?.off === 'function') oldListener.off();
      }

      gunUnsub = room.map().on((data, senderAddr) => {
        if (senderAddr === self.userId) {
          console.debug('🔄 P2P: skipping own message');
          return;
        }
        
        try {
          const payload = typeof data === 'string' ? JSON.parse(data) : data;
          
          onMessage({
            sender: senderAddr,
            encryptedPayload: payload,
            timestamp: payload.ts || Date.now(),
            tx_id: payload.tx_id,
            via: 'gun'
          });
        } catch (e) {
          console.warn('⚠️ P2P parse error:', e);
        }
      });
      
      this.subscriptions.set(key, { off: () => gunUnsub?.off?.() });
      console.debug(`✅ Gun subscribed: ${chatId.substring(0, 20)}...`);
    }

    this._startPolling(chatId, onMessage);

    return () => {
      if (gunUnsub && typeof gunUnsub.off === 'function') {
        gunUnsub.off();
      }
      this.subscriptions.delete(key);
      this._stopPolling(chatId);
      console.debug(`🔕 Unsubscribed: ${chatId.substring(0, 20)}...`);
    };
  }

  _startPolling(chatId, onMessage) {
    if (this.pollIntervals.has(chatId)) {
      console.debug('🔄 Polling already active for:', chatId.substring(0, 20) + '...');
      return;
    }
    
    this.lastSync.set(chatId, 0);
    let retryCount = 0;
    const MAX_RETRY = 5;
    const BASE_INTERVAL = 2000;
    let active = true;

    const poll = async () => {
      if (!active) return;
      
      try {
        const since = this.lastSync.get(chatId) || 0;
        const res = await fetch(`/p2p-poll?chat=${encodeURIComponent(chatId)}&since=${since}`, {
          cache: 'no-store'
        });

        if (res.ok) {
          retryCount = 0;
          const messages = await res.json();

          if (Array.isArray(messages) && messages.length > 0) {
            console.debug(`📥 Poll received ${messages.length} messages for ${chatId.substring(0, 16)}...`);
            
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
            });
          }
        } else if (res.status === 404) {
          console.debug('ℹ️ P2P polling endpoint not available, using Gun only');
          active = false;
          return;
        }
      } catch (e) {
        retryCount = Math.min(retryCount + 1, MAX_RETRY);
        console.debug(`ℹ️ P2P poll error (retry ${retryCount}/${MAX_RETRY}):`, e.message);
      }

      if (active) {
        const nextDelay = BASE_INTERVAL * Math.pow(1.5, retryCount);
        setTimeout(poll, nextDelay);
      }
    };

    poll();
    
    this.pollIntervals.set(chatId, { 
      active: () => active,
      stop: () => { active = false; }
    });
    
    console.debug(`🔄 Started long polling for: ${chatId.substring(0, 20)}...`);
  }

  _stopPolling(chatId) {
    const entry = this.pollIntervals.get(chatId);
    if (entry) {
      if (typeof entry.stop === 'function') entry.stop();
      this.pollIntervals.delete(chatId);
      this.lastSync.delete(chatId);
      console.debug(`🛑 Stopped polling for: ${chatId.substring(0, 20)}...`);
    }
  }

  async send(chatId, encryptedPayload, txId) {
    if (!window.GunConfig?.gun) {
      console.warn('⚠️ P2PSync.send: Gun not available');
      return { via: 'none', delivered: false };
    }

    const room = window.GunConfig.getRoom(chatId);
    if (!room) {
      console.warn('⚠️ P2PSync.send: room not available');
      return { via: 'none', delivered: false };
    }

    const packet = {
      ...encryptedPayload,
      ts: Date.now(),
      tx_id: txId,
      sender_addr: this.userId
    };

    try {
      room.get(this.userId).put(packet);
      console.debug(`📤 P2P sent to ${chatId.substring(0, 16)}... tx:${txId?.substring(0, 8)}`);
      return { via: 'gun', delivered: true };
    } catch (e) {
      console.error('❌ P2PSync.send error:', e);
      return { via: 'gun', delivered: false, error: e.message };
    }
  }

  unsubscribeAll() {
    console.log('🧹 P2PSync: unsubscribing from all chats');
    
    for (const [key, sub] of this.subscriptions) {
      if (typeof sub?.off === 'function') {
        sub.off();
      }
    }
    this.subscriptions.clear();
    
    for (const [chatId] of this.pollIntervals) {
      this._stopPolling(chatId);
    }
    this.pollIntervals.clear();
    this.lastSync.clear();
  }

  getDebugInfo() {
    return {
      activeSubscriptions: Array.from(this.subscriptions.keys()),
      activePolling: Array.from(this.pollIntervals.keys()),
      lastSync: Object.fromEntries(this.lastSync)
    };
  }
}

window.P2PSync = P2PSync;

