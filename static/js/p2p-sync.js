/**
 * p2p-sync.js — P2P Sync with Long Polling Fallback
 * 🔔 Handles message delivery only (notifications in NotificationManager)
 */

(function() {
  'use strict';

  const DEBUG = process.env.NODE_ENV !== 'production';

  class P2PSync {
    constructor() {
      this.subscriptions = new Map();
      this.pollIntervals = new Map();
      this.lastSync = new Map();
      this.userId = window.GunConfig?.userId;
      this.retryCount = new Map();
    }

    /**
     * Subscribe to chat messages
     * @param {string} chatId - Chat identifier
     * @param {Function} onMessage - Message handler callback
     * @returns {Function} Unsubscribe function
     */
    subscribe(chatId, onMessage) {
      if (!chatId || typeof onMessage !== 'function') {
        console.error('❌ P2PSync.subscribe: invalid arguments');
        return () => {};
      }

      const room = window.GunConfig?.getRoom?.(chatId);
      const key = `sub_${chatId}`;
      let gunUnsub = null;

      // Gun subscription
      if (window.GunConfig?.gun && room) {
        // Cleanup existing subscription
        if (this.subscriptions.has(key)) {
          const old = this.subscriptions.get(key);
          old?.off?.();
        }

        gunUnsub = room.map().on((data, senderAddr) => {
          // Skip own messages
          if (senderAddr === this.userId) {
            if (DEBUG) console.debug('🔄 P2P: skipping own message');
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

        this.subscriptions.set(key, {
          off: () => gunUnsub?.off?.(),
          type: 'gun'
        });
        if (DEBUG) console.debug(`✅ Gun subscribed: ${chatId.slice(0, 16)}...`);
      }

      // Start polling fallback
      this._startPolling(chatId, onMessage);

      // Return unsubscribe function
      return () => {
        gunUnsub?.off?.();
        this.subscriptions.delete(key);
        this._stopPolling(chatId);
        if (DEBUG) console.debug(`🔕 Unsubscribed: ${chatId.slice(0, 16)}...`);
      };
    }

    /**
     * Start long polling for chat
     * @private
     */
    _startPolling(chatId, onMessage) {
      if (this.pollIntervals.has(chatId)) return;

      this.lastSync.set(chatId, 0);
      this.retryCount.set(chatId, 0);

      const BASE_INTERVAL = 2000;
      const MAX_RETRY = 5;
      let active = true;

      const poll = async () => {
        if (!active) return;

        try {
          const since = this.lastSync.get(chatId) || 0;
          const res = await fetch(
            `/p2p-poll?chat=${encodeURIComponent(chatId)}&since=${since}`,
            { cache: 'no-store' }
          );

          if (res.ok) {
            this.retryCount.set(chatId, 0);
            const messages = await res.json();

            if (Array.isArray(messages) && messages.length > 0) {
              if (DEBUG) {
                console.debug(`📥 Poll: ${messages.length} messages for ${chatId.slice(0, 16)}...`);
              }

              messages.forEach(msg => {
                const ts = msg.ts > 1e10 ? msg.ts : msg.ts * 1000;

                if (ts > (this.lastSync.get(chatId) || 0)) {
                  this.lastSync.set(chatId, ts);
                }

                onMessage({
                  sender: msg.sender,
                  encryptedPayload: {
                    content: msg.content,
                    image: msg.image,
                    version: 'hybrid-v2',
                    tx_id: msg.tx_id
                  },
                  timestamp: ts,
                  tx_id: msg.tx_id,
                  via: 'poll'
                });
              });
            }
          } else if (res.status === 404) {
            if (DEBUG) console.debug('ℹ️ Polling endpoint not available');
            active = false;
            return;
          }
        } catch (e) {
          const retries = this.retryCount.get(chatId) || 0;
          const nextRetries = Math.min(retries + 1, MAX_RETRY);
          this.retryCount.set(chatId, nextRetries);

          if (DEBUG) {
            console.debug(`ℹ️ Poll error (${nextRetries}/${MAX_RETRY}):`, e.message);
          }
        }

        if (active) {
          const retries = this.retryCount.get(chatId) || 0;
          const delay = BASE_INTERVAL * Math.pow(1.5, retries);
          setTimeout(poll, delay);
        }
      };

      poll();

      this.pollIntervals.set(chatId, {
        active: () => active,
        stop: () => { active = false; }
      });

      if (DEBUG) console.debug(`🔄 Started polling: ${chatId.slice(0, 16)}...`);
    }

    /**
     * Stop polling for chat
     * @private
     */
    _stopPolling(chatId) {
      const entry = this.pollIntervals.get(chatId);
      if (entry) {
        entry.stop?.();
        this.pollIntervals.delete(chatId);
        this.lastSync.delete(chatId);
        this.retryCount.delete(chatId);
        if (DEBUG) console.debug(`🛑 Stopped polling: ${chatId.slice(0, 16)}...`);
      }
    }

    /**
     * Send message via P2P
     * @param {string} chatId - Chat identifier
     * @param {Object} encryptedPayload - Encrypted message data
     * @param {string} txId - Transaction ID
     * @returns {Promise<Object>} Delivery status
     */
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
        if (DEBUG) {
          console.debug(`📤 P2P sent: ${chatId.slice(0, 16)}... tx:${txId?.slice(0, 8)}`);
        }
        return { via: 'gun', delivered: true };
      } catch (e) {
        console.error('❌ P2PSync.send error:', e);
        return { via: 'gun', delivered: false, error: e.message };
      }
    }

    /**
     * Unsubscribe from all chats
     */
    unsubscribeAll() {
      if (DEBUG) console.log('🧹 P2PSync: unsubscribing all');

      for (const [key, sub] of this.subscriptions) {
        sub?.off?.();
      }
      this.subscriptions.clear();

      for (const [chatId] of this.pollIntervals) {
        this._stopPolling(chatId);
      }
      this.pollIntervals.clear();
      this.lastSync.clear();
      this.retryCount.clear();
    }

    /**
     * Get debug information
     * @returns {Object} Debug stats
     */
    getDebugInfo() {
      return {
        mode: window.GunConfig?.mode,
        activeSubscriptions: Array.from(this.subscriptions.keys()),
        activePolling: Array.from(this.pollIntervals.keys()),
        lastSync: Object.fromEntries(this.lastSync)
      };
    }
  }

  // Export to global scope
  window.P2PSync = P2PSync;

})();