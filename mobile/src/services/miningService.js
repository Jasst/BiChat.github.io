// src/services/miningService.js — реальный майнинг через API
import { getLastProof, mineBlock } from '../api';

const BLOCKCOIN_SATS = 1_000_000;

class MiningService {
  constructor() {
    this.isMining = false;
    this.callbacks = {};
    this.abortController = null;
  }

  setCallbacks(callbacks) {
    this.callbacks = {
      onProgress: () => {},
      onBlockFound: () => {},
      onError: () => {},
      onStopped: () => {},
      ...callbacks,
    };
  }

  async startMining() {
    if (this.isMining) return;
    this.isMining = true;
    this.abortController = new AbortController();

    try {
      const chainData = await getLastProof();
      this.runMiningLoop(chainData);
    } catch (err) {
      this.callbacks.onError?.(err);
      this.stopMining();
    }
  }

  async runMiningLoop(chainData) {
    if (!this.isMining) return;

    let { last_proof, last_index, difficulty, challenge } = chainData;
    const maxIter = 5000000;
    let proof = 0;
    const startTime = Date.now();
    const target = '0'.repeat(difficulty);
    const BATCH_SIZE = 500;

    const mineBatch = async () => {
      if (!this.isMining) return;

      const batchPromises = [];
      const batchProofs = [];

      for (let i = 0; i < BATCH_SIZE && (proof + i) < maxIter; i++) {
        const currentProof = proof + i;
        const message = `${last_proof}${challenge}${currentProof}`;
        batchProofs.push(currentProof);
        batchPromises.push(this.sha256(message));
      }

      const hashes = await Promise.all(batchPromises);

      for (let i = 0; i < hashes.length; i++) {
        if (hashes[i].startsWith(target)) {
          // Блок найден! Отправляем на сервер
          try {
            const result = await mineBlock(batchProofs[i], challenge, last_proof, last_index);
            this.isMining = false;
            this.callbacks.onBlockFound?.({ reward: result.reward || 50 * BLOCKCOIN_SATS });
            return;
          } catch (err) {
            if (err.message?.includes('409') || err.message?.includes('conflict')) {
              const fresh = await getLastProof();
              this.runMiningLoop(fresh);
              return;
            }
            this.callbacks.onError?.(err);
            this.stopMining();
            return;
          }
        }
      }

      proof += batchPromises.length;

      // Прогресс каждые ~50k итераций
      if (proof % 50000 < BATCH_SIZE) {
        const elapsedSec = (Date.now() - startTime) / 1000;
        const hashrate = proof / elapsedSec;
        const remaining = maxIter - proof;
        const etaSec = hashrate > 0 ? remaining / hashrate : Infinity;
        const percent = Math.min((proof / maxIter) * 100, 100);

        this.callbacks.onProgress?.({
          progress: proof,
          maxIter,
          hashrate: Math.floor(hashrate),
          eta: etaSec,
          percent,
        });

        // Даём UI подышать
        await new Promise(r => setTimeout(r, 0));
      }

      // Следующий батч
      if (proof < maxIter && this.isMining) {
        setTimeout(mineBatch, 0);
      } else if (this.isMining) {
        // Не нашли — перезапускаем
        const fresh = await getLastProof();
        this.runMiningLoop(fresh);
      }
    };

    mineBatch();
  }

  async sha256(message) {
    const encoder = new TextEncoder();
    const data = encoder.encode(message);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = new Uint8Array(hashBuffer);
    let hex = '';
    for (let i = 0; i < hashArray.length; i++) {
      hex += hashArray[i].toString(16).padStart(2, '0');
    }
    return hex;
  }

  stopMining() {
    this.isMining = false;
    this.callbacks.onStopped?.();
  }
}

export default new MiningService();