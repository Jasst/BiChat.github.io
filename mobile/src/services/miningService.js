// src/services/miningService.js
import { sha256 } from 'js-sha256';
import { getLastProof, mineBlock } from '../api';

const BLOCKCOIN_SATS = 1_000_000;

class MiningService {
  constructor() {
    this.isMining = false;
    this.callbacks = {};
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

    try {
      const chainData = await getLastProof();
      this.runMiningLoop(chainData);
    } catch (err) {
      this.callbacks.onError?.(err);
      this.stopMining();
    }
  }

  restartMining() {
    const wasRunning = this.isMining;
    this.isMining = false;
    if (wasRunning) this.callbacks.onStopped?.();
    setTimeout(() => this.startMining(), 500);
  }

  async runMiningLoop(chainData) {
    if (!this.isMining) return;

    let { last_proof, last_index, difficulty, challenge } = chainData;
    const maxIter = 5000000;
    let proof = 0;
    const startTime = Date.now();
    const target = '0'.repeat(difficulty);
    const BATCH_SIZE = 20000;

    while (this.isMining && proof < maxIter) {
      const limit = Math.min(BATCH_SIZE, maxIter - proof);
      const batchProofs = [];
      const hashes = [];

      for (let i = 0; i < limit; i++) {
        const currentProof = proof + i;
        batchProofs.push(currentProof);
        hashes.push(sha256(`${last_proof}${challenge}${currentProof}`));
      }

      for (let i = 0; i < hashes.length; i++) {
        if (hashes[i].startsWith(target)) {
          this.isMining = false;
          try {
            const result = await mineBlock(batchProofs[i], challenge, last_proof, last_index);
            this.callbacks.onBlockFound?.({ reward: result.reward || 50 * BLOCKCOIN_SATS });
            return;
          } catch (err) {
            if (err.message?.includes('409') || err.message?.includes('conflict')) {
              try {
                const fresh = await getLastProof();
                this.runMiningLoop(fresh);
                return;
              } catch (e2) {
                this.callbacks.onError?.(e2);
                this.stopMining();
                return;
              }
            }
            this.callbacks.onError?.(err);
            this.stopMining();
            return;
          }
        }
      }

      proof += limit;

      if (proof % 50000 < limit) {
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

        await new Promise(r => setTimeout(r, 0));
      }
    }

    if (this.isMining) {
      try {
        const fresh = await getLastProof();
        this.runMiningLoop(fresh);
      } catch (err) {
        this.callbacks.onError?.(err);
        this.stopMining();
      }
    }
  }

  stopMining() {
    const wasRunning = this.isMining;
    this.isMining = false;
    if (wasRunning) this.callbacks.onStopped?.();
  }
}

export default new MiningService();