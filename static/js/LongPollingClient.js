/**
 * LongPollingClient.js — клиент для Long Polling с авто-переподключением
 */
(function() {
    if (window.LongPollingClientLoaded) return;
    window.LongPollingClientLoaded = true;

    class LongPollingClient {
        constructor(options = {}) {
            this.baseUrl = options.baseUrl || '';
            this.timeout = options.timeout || 25000;
            this.onMessages = options.onMessages || (() => {});
            this.onError = options.onError || (() => {});
            this.onConnect = options.onConnect || (() => {});
            this.onDisconnect = options.onDisconnect || (() => {});

            this.isRunning = false;
            this.isConnected = false;
            this.lastTimestamp = Date.now() / 1000;
            this.retryDelay = options.retryDelay || 3000;
            this.maxRetries = options.maxRetries || 10;
            this.retryCount = 0;
            this.currentRequest = null;
            this.abortController = null;

            this.maxTimeout = Math.min(options.timeout || 25000, 30000);
            this.maxTimestampDrift = 60;
            this.debug = options.debug || false;
            this._reconnectLock = false;

            this._processedMessageIds = new Set();
            this._maxCachedIds = 100;
        }

        log(...args) {
            if (this.debug) console.log('[LongPolling]', ...args);
        }

        async start() {
            if (this.isRunning) return;
            this.isRunning = true;
            this.retryCount = 0;
            this._reconnectLock = false;
            this.log('Starting Long Polling client');
            if (!this._isSessionValid()) {
                this.log('Session invalid, not starting');
                this.isRunning = false;
                return;
            }
            this._poll();
        }

        stop() {
            this.log('Stopping');
            this.isRunning = false;
            this.isConnected = false;
            this._reconnectLock = true;
            if (this.abortController) {
                this.abortController.abort();
                this.abortController = null;
            }
            this.currentRequest = null;
            // ✅ Очистка кэша ID сообщений
            this._processedMessageIds.clear();
            this.onDisconnect();
        }

        forceCheck() {
            if (this.abortController && !this.abortController.signal.aborted) {
                this.abortController.abort();
                this.log('Forced check');
            }
        }

        updateTimestamp(timestamp) {
            const now = Date.now() / 1000;
            if (timestamp > now + this.maxTimestampDrift) return;
            if (timestamp > this.lastTimestamp) {
                this.lastTimestamp = timestamp;
                this.log(`Timestamp updated to ${this.lastTimestamp}`);
            }
        }

        markMessageProcessed(messageId) {
            this._processedMessageIds.add(messageId);
            if (this._processedMessageIds.size > this._maxCachedIds) {
                const toDelete = Array.from(this._processedMessageIds).slice(0, this._maxCachedIds / 2);
                toDelete.forEach(id => this._processedMessageIds.delete(id));
            }
        }

        isMessageProcessed(messageId) {
            return this._processedMessageIds.has(messageId);
        }

        _isSessionValid() {
            return window.AppData && window.AppData.userAddress;
        }

        _sanitizeTimestamp(ts) {
            const now = Date.now() / 1000;
            const minValid = now - 3600;
            const maxValid = now + 60;
            let sanitized = Math.max(ts, minValid);
            sanitized = Math.min(sanitized, maxValid);
            if (sanitized !== ts) this.log(`⚠️ Timestamp sanitized: ${ts} → ${sanitized}`);
            return sanitized;
        }

        async _poll() {
            while (this.isRunning && !this._reconnectLock) {
                try {
                    this.abortController = new AbortController();
                    const safeTimestamp = this._sanitizeTimestamp(this.lastTimestamp);
                    const requestTimeout = Math.min(25, Math.floor(this.maxTimeout / 1000));
                    const url = `${this.baseUrl}/wait_for_messages?since=${safeTimestamp}&timeout=${requestTimeout}`;
                    this.log(`Requesting: ${url}`);

                    const fetchTimeout = setTimeout(() => this.abortController?.abort(), 30000);
                    const response = await fetch(url, {
                        method: 'GET',
                        headers: {
                            'Cache-Control': 'no-cache, no-store',
                            'Pragma': 'no-cache',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        signal: this.abortController.signal,
                        credentials: 'same-origin'
                    });
                    clearTimeout(fetchTimeout);

                    if (!response.ok) {
                        if (response.status === 401 || response.status === 403) {
                            this.log(`Session expired (${response.status})`);
                            this.stop();
                            break;
                        }
                        throw new Error(`HTTP ${response.status}`);
                    }

                    const data = await response.json();
                    this.retryCount = 0;
                    if (!this.isConnected) {
                        this.isConnected = true;
                        this.onConnect();
                    }

                    if (data.messages?.length) {
                        const newMessages = data.messages.filter(msg => msg.id && !this.isMessageProcessed(msg.id));
                        this.log(`Received ${data.messages.length} messages, ${newMessages.length} new`);
                        if (newMessages.length) {
                            newMessages.forEach(msg => this.markMessageProcessed(msg.id));
                            const lastMsg = newMessages[newMessages.length - 1];
                            if (lastMsg.timestamp) this.updateTimestamp(lastMsg.timestamp);
                            this.onMessages(newMessages);
                        }
                    } else {
                        this.log('No new messages');
                    }
                    await this._delay(100);
                } catch (error) {
                    if (error.name === 'AbortError') {
                        this.log('Request aborted');
                        continue;
                    }
                    console.error('Long polling error:', error);
                    this.retryCount++;
                    if (this.isConnected) {
                        this.isConnected = false;
                        this.onDisconnect();
                    }
                    this.onError(new Error('Connection issue'));
                    const delay = Math.min(this.retryDelay * Math.pow(2, this.retryCount), 30000);
                    this.log(`Retry ${this.retryCount}/${this.maxRetries} in ${delay}ms`);
                    if (this.retryCount >= this.maxRetries) {
                        this.log('Max retries reached');
                        this.stop();
                        break;
                    }
                    await this._delay(delay);
                } finally {
                    this.currentRequest = null;
                    this.abortController = null;
                }
            }
        }

        _delay(ms) {
            return new Promise(resolve => setTimeout(resolve, ms));
        }

        getStatus() {
            return {
                isRunning: this.isRunning,
                isConnected: this.isConnected,
                retryCount: this.retryCount,
                processedCount: this._processedMessageIds.size
            };
        }
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = LongPollingClient;
    }
    if (typeof window !== 'undefined') {
        window.LongPollingClient = LongPollingClient;
    }
})();