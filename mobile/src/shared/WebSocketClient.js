/**
 * WebSocketClient.js — клиент для WebSocket с авто-переподключением
 * Адаптирован для React Native
 *
 * ИСПРАВЛЕНИЯ:
 * 1. reconnectDelay сбрасывается до начального значения после успешного подключения
 * 2. Добавлен метод send() с проверкой готовности соединения
 * 3. Добавлен публичный метод getState() для диагностики
 * 4. Убраны зависимости от window (браузерное окружение)
 * 5. Экспорт по умолчанию (ES Module)
 */

class WebSocketClient {
  constructor(options = {}) {
    // URL должен быть передан явно (из constants.js)
    this.url = options.url || null;
    this.onMessage    = options.onMessage    || (() => {});
    this.onError      = options.onError      || (() => {});
    this.onConnect    = options.onConnect    || (() => {});
    this.onDisconnect = options.onDisconnect || (() => {});
    this.useAuthentication = options.useAuthentication !== false;
    this.debug = options.debug || false;

    this.ws = null;
    this.isConnected = false;

    this._initialReconnectDelay = options.reconnectDelay || 3000;
    this.reconnectDelay = this._initialReconnectDelay;
    this.maxReconnectDelay = 30000;
    this.reconnectTimer = null;
    this.shouldReconnect = true;

    this.address   = null;
    this.signature = null;
    this.nonce     = null;
  }

  setAuth(address, signature, nonce) {
    this.address   = address;
    this.signature = signature;
    this.nonce     = nonce;
  }

  connect() {
    if (this.ws && (
      this.ws.readyState === WebSocket.OPEN ||
      this.ws.readyState === WebSocket.CONNECTING
    )) {
      this.log('Already connected or connecting');
      return;
    }

    if (!this.url) {
      throw new Error('WebSocket URL not provided. Please set options.url');
    }

    let finalUrl = this.url;
    if (this.useAuthentication && this.address && this.signature && this.nonce) {
      finalUrl += `?address=${encodeURIComponent(this.address)}&signature=${encodeURIComponent(this.signature)}&nonce=${encodeURIComponent(this.nonce)}`;
    }

    this.log('Connecting to WebSocket:', finalUrl);
    this.ws = new WebSocket(finalUrl);
    this.ws.onopen    = ()      => this._onOpen();
    this.ws.onmessage = (event) => this._onMessage(event);
    this.ws.onerror   = (error) => this._onError(error);
    this.ws.onclose   = (event) => this._onClose(event);
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.isConnected = false;
  }

  send(data) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.log('Cannot send: socket not open');
      return false;
    }
    try {
      this.ws.send(typeof data === 'string' ? data : JSON.stringify(data));
      return true;
    } catch (e) {
      this.log('Send error:', e);
      return false;
    }
  }

  getState() {
    const states = { 0: 'CONNECTING', 1: 'OPEN', 2: 'CLOSING', 3: 'CLOSED' };
    return {
      readyState: this.ws ? states[this.ws.readyState] : 'NO_SOCKET',
      isConnected: this.isConnected,
      reconnectDelay: this.reconnectDelay
    };
  }

  _onOpen() {
    this.isConnected = true;
    this.reconnectDelay = this._initialReconnectDelay;
    this.log('WebSocket connected, reconnect delay reset to', this.reconnectDelay);
    this.onConnect();
  }

  _onMessage(event) {
    try {
      const data = JSON.parse(event.data);
      this.log('Received:', data);
      this.onMessage(data);
    } catch (e) {
      this.log('Invalid JSON:', event.data);
    }
  }

  _onError(error) {
    this.log('WebSocket error:', error);
    this.onError(error);
  }

  _onClose(event) {
    this.log('WebSocket closed, code:', event.code);
    this.isConnected = false;
    this.onDisconnect();
    if (this.shouldReconnect && event.code !== 1008) {
      this._scheduleReconnect();
    }
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.log(`Scheduling reconnect in ${this.reconnectDelay}ms`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
    }, this.reconnectDelay);
  }

  log(...args) {
    if (this.debug) console.log('[WebSocketClient]', ...args);
  }
}

export default WebSocketClient;