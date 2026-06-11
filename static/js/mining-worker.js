// static/js/mining-worker.js
self.onmessage = async function(e) {
    const { last_proof, challenge, difficulty, maxIter, startTime } = e.data;
    const target = '0'.repeat(difficulty);

    for (let proof = 0; proof < maxIter; proof++) {
        const hash = await sha256(`${last_proof}${challenge}${proof}`);
        if (hash.startsWith(target)) {
            self.postMessage({ found: true, proof, elapsed: Date.now() - startTime });
            return;
        }
        // Отправляем прогресс с хешрейтом и ETA каждые 10k итераций
        if (proof % 100000 === 0) {
            const elapsedSec = (Date.now() - startTime) / 1000;
            const hashrate = proof / elapsedSec;
            const remaining = maxIter - proof;
            const etaSec = remaining / hashrate;
            self.postMessage({
                progress: proof,
                maxIter,
                hashrate: Math.floor(hashrate),
                eta: etaSec
            });
        }
    }
    self.postMessage({ found: false });
};

async function sha256(message) {
    const encoder = new TextEncoder();
    const data = encoder.encode(message);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}