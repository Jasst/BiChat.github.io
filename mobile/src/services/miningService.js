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
    if (this.isMining) {
      console.log('⛔ [MiningService] already running, ignored');
      return;
    }
    this.isMining = true;
    console.log('🚀 [MiningService] startMining() called');

    try {
      const chainData = await getLastProof();
      console.log('📡 [MiningService] last-proof OK:', JSON.stringify(chainData));
      this.runMiningLoop(chainData);
    } catch (err) {
      console.error('💥 [MiningService] getLastProof FAILED:', err.message);
      this.callbacks.onError?.(err);
      this.stopMining();
    }
  }

  restartMining() {
    console.log('🔔 [MiningService] restartMining() called, isMining=', this.isMining);

    // Сначала полностью останавливаем
    const wasRunning = this.isMining;
    this.isMining = false;

    // Вызываем onStopped ТОЛЬКО если был запущен (чтобы UI сбросил прогресс)
    if (wasRunning) {
      this.callbacks.onStopped?.();
    }

    // Ждём 500мс и перезапускаем
    setTimeout(() => {
      console.log('🔄 [MiningService] auto-restarting after new_block...');
      // НЕ вызываем stopMining() повторно — сразу стартуем
      this.startMining();
    }, 500);
  }

    async runMiningLoop(chainData) {
    if (!this.isMining) {
      console.log('⛔ [MiningService] runMiningLoop: isMining=false, exit');
      return;
    }

    let { last_proof, last_index, difficulty, challenge } = chainData;
    const maxIter = 5000000;
    let proof = 0;
    const startTime = Date.now();
    const target = '0'.repeat(difficulty);
    const BATCH_SIZE = 20000;

    console.log(`⛏️ [MiningService] loop started | diff=${difficulty} | target="${target}" | maxIter=${maxIter}`);

    while (this.isMining && proof < maxIter) {
      const limit = Math.min(BATCH_SIZE, maxIter - proof);
      const batchProofs = [];
      const hashes = [];

      // Генерируем пакет хешей
      for (let i = 0; i < limit; i++) {
        const currentProof = proof + i;
        batchProofs.push(currentProof);
        hashes.push(sha256(`${last_proof}${challenge}${currentProof}`));
      }

      // Проверяем пакет
      for (let i = 0; i < hashes.length; i++) {
        if (hashes[i].startsWith(target)) {
          console.log('🎯 [MiningService] BLOCK FOUND! proof=', batchProofs[i], 'hash=', hashes[i]);
          this.isMining = false;

          try {
            const result = await mineBlock(batchProofs[i], challenge, last_proof, last_index);
            console.log('✅ [MiningService] mineBlock server response:', JSON.stringify(result));
            this.callbacks.onBlockFound?.({ reward: result.reward || 50 * BLOCKCOIN_SATS });
            return;
          } catch (err) {
            console.warn('⚠️ [MiningService] mineBlock rejected:', err.message);

            if (err.message?.includes('409') || err.message?.includes('conflict')) {
              console.log('🔄 [MiningService] 409 conflict, fetching fresh proof...');
              try {
                const fresh = await getLastProof();
                console.log('📡 [MiningService] fresh proof after conflict:', JSON.stringify(fresh));
                this.runMiningLoop(fresh);
                return;
              } catch (e2) {
                console.error('💥 [MiningService] failed to get fresh proof:', e2.message);
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

      // Прогресс + даём UI подышать каждые ~50k
      if (proof % 50000 < limit) {
        const elapsedSec = (Date.now() - startTime) / 1000;
        const hashrate = proof / elapsedSec;
        const remaining = maxIter - proof;
        const etaSec = hashrate > 0 ? remaining / hashrate : Infinity;
        const percent = Math.min((proof / maxIter) * 100, 100);

        console.log(
          `⏳ [MiningService] progress ${percent.toFixed(2)}% | ` +
          `hashes=${proof} | ${Math.floor(hashrate).toLocaleString()} h/s | ` +
          `ETA ${etaSec === Infinity ? '∞' : (etaSec / 60).toFixed(1) + ' min'}`
        );

        this.callbacks.onProgress?.({
          progress: proof,
          maxIter,
          hashrate: Math.floor(hashrate),
          eta: etaSec,
          percent,
        });

        // Короткая пауза, чтобы React Native не завис
        await new Promise(r => setTimeout(r, 0));
      }
    }

    // Если дошли до maxIter и майнинг всё ещё активен — перезапускаем с новым proof
    if (this.isMining) {
      console.log('🔁 [MiningService] maxIter reached, no block. Restarting loop...');
      try {
        const fresh = await getLastProof();
        this.runMiningLoop(fresh);
      } catch (err) {
        console.error('💥 [MiningService] failed to restart loop:', err.message);
        this.callbacks.onError?.(err);
        this.stopMining();
      }
    } else {
      console.log('🛑 [MiningService] loop ended (mining stopped)');
    }
  }

  stopMining() {
    const wasRunning = this.isMining;
    this.isMining = false;
    console.log('🛑 [MiningService] stopMining() called, wasRunning=', wasRunning);
    this.callbacks.onStopped?.();
  }
}

export default new MiningService();