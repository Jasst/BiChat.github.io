/**
 * LongPollingClient.js — клиент для Long Polling с авто-переподключением
 * Использует /wait_for_messages эндпоинт вместо частых запросов
 */

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

        // Для отладки
        this.debug = options.debug || false;
    }

    log(...args) {
        if (this.debug) {
            console.log('[LongPolling]', ...args);
        }
    }

    async start() {
        if (this.isRunning) {
            this.log('Already running');
            return;
        }

        this.isRunning = true;
        this.retryCount = 0;
        this.log('Starting Long Polling client');
        this._poll();
    }

    stop() {
        this.log('Stopping Long Polling client');
        this.isRunning = false;
        this.isConnected = false;

        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }

        if (this.currentRequest) {
            this.currentRequest = null;
        }

        this.onDisconnect();
    }

    // Принудительно сбросить таймер (вызвать после отправки сообщения)
    forceCheck() {
        if (this.abortController) {
            this.abortController.abort();
            this.log('Forced check - aborted current wait');
        }
    }

    // Обновить timestamp (после загрузки старых сообщений)
    updateTimestamp(timestamp) {
        if (timestamp > this.lastTimestamp) {
            this.lastTimestamp = timestamp;
            this.log(`Timestamp updated to ${this.lastTimestamp}`);
        }
    }

    async _poll() {
        while (this.isRunning) {
            try {
                // Создаём AbortController для таймаута
                this.abortController = new AbortController();

                const url = `${this.baseUrl}/wait_for_messages?since=${this.lastTimestamp}&timeout=25`;
                this.log(`Requesting: ${url}`);

                this.currentRequest = fetch(url, {
                    method: 'GET',
                    headers: {
                        'Cache-Control': 'no-cache',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    signal: this.abortController.signal
                });

                const response = await this.currentRequest;

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const data = await response.json();

                // Сброс счётчика ошибок при успехе
                this.retryCount = 0;

                // Обновляем статус соединения
                if (!this.isConnected) {
                    this.isConnected = true;
                    this.onConnect();
                }

                // Обрабатываем сообщения
                if (data.messages && data.messages.length > 0) {
                    this.log(`Received ${data.messages.length} new messages`);

                    // Обновляем timestamp на основе последнего сообщения
                    const lastMsg = data.messages[data.messages.length - 1];
                    if (lastMsg.timestamp > this.lastTimestamp) {
                        this.lastTimestamp = lastMsg.timestamp + 0.001;
                    }

                    // Вызываем callback
                    this.onMessages(data.messages);
                } else {
                    this.log('No new messages, waiting...');
                }

                // Небольшая задержка перед следующим запросом (предотвращает гонки)
                await this._delay(50);

            } catch (error) {
                // Проверяем, не был ли это intentional abort
                if (error.name === 'AbortError') {
                    this.log('Request aborted (likely forceCheck)');
                    // Не считаем ошибкой, просто продолжаем
                    continue;
                }

                // Ошибка соединения
                console.error('Long polling error:', error);
                this.retryCount++;

                if (this.isConnected) {
                    this.isConnected = false;
                    this.onDisconnect();
                }

                this.onError(error);

                // Экспоненциальная задержка при ошибках
                const delay = Math.min(this.retryDelay * Math.pow(2, this.retryCount), 30000);
                this.log(`Retry ${this.retryCount}/${this.maxRetries} in ${delay}ms`);

                if (this.retryCount >= this.maxRetries) {
                    this.log('Max retries reached, stopping...');
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

    // Получить статус
    getStatus() {
        return {
            isRunning: this.isRunning,
            isConnected: this.isConnected,
            retryCount: this.retryCount,
            lastTimestamp: this.lastTimestamp
        };
    }
}

// Экспортируем для использования в других скриптах
if (typeof module !== 'undefined' && module.exports) {
    module.exports = LongPollingClient;
}