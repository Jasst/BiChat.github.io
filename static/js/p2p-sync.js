/**
 * p2p-sync.js — P2P-синхронизация для УЖЕ ЗАШИФРОВАННЫХ сообщений
 */
class P2PSync {
  constructor() {
    this.subscriptions = new Map();
  }

  subscribe(chatId, onMessage) {
    const room = window.GunConfig.getRoom(chatId);
    const key = `sub_${chatId}`;

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
          tx_id: payload.tx_id
        });
      } catch (e) {
        console.warn('⚠️ P2P parse error:', e);
      }
    });

    this.subscriptions.set(key, listener);
    return () => listener.off();
  }

  async send(chatId, encryptedPayload, txId) {
    const room = window.GunConfig.getRoom(chatId);
    const packet = {
      ...encryptedPayload,
      ts: Date.now(),
      tx_id: txId,
      sender_addr: window.GunConfig.userId
    };
    room.get(window.GunConfig.userId).put(packet);
    return { via: 'p2p', delivered: true };
  }

  unsubscribeAll() {
    for (const [, listener] of this.subscriptions) listener.off();
    this.subscriptions.clear();
  }
}
window.P2PSync = P2PSync;