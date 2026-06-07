// wallet.js — полностью интернационализированная версия
(function() {
  if (window._walletScriptLoaded) return;
  window._walletScriptLoaded = true;

  // Helper for i18n
  function t(key, opts) {
    if (typeof i18next !== 'undefined' && i18next.t) {
      return i18next.t(key, opts);
    }
    // Fallback English for keys used in this file
    const fallbacks = {
      'mining_getting_proof': 'Mining... getting current proof',
      'mining_difficulty': 'Mining... difficulty={difficulty}, max tries={tries}M',
      'hashing_progress': 'Hashing... {current}k / {total}k | {elapsed}s',
      'block_found': '🎉 BLOCK FOUND!',
      'block_mined': 'Block mined! +{reward} BlockCoin',
      'block_mined_toast': '⛏ Block mined! +{reward} BlockCoin',
      'mining_failed': 'Mining failed',
      'network_error_submit': 'Network error during submit',
      'network_error': 'Network error',
      'mining_error': 'Mining error: {message}',
      'mining_stopped': 'Stopped',
      'amount_empty': 'Amount field is empty',
      'invalid_amount': 'Enter a valid positive number',
      'staked_success': 'Staked! Unlocks at block {block}',
      'unstaked_success': 'Unstaked!',
      'no_active_stakes': 'No active stakes',
      'balance_updated': 'Balance updated',
      'network_stats_updated': 'Network stats updated',
      'no_transactions': 'No transactions yet',
      'failed_to_load': 'Failed to load',
      'lottery_reward': '🎁 Lottery Reward',
      'fee': '💸 Fee',
      'sent': '📤 Sent',
      'received': '📥 Received',
      'block_reward': '⛏ Block Reward',
      'stake_label': '🔒 Stake',
      'unstake_label': '🔓 Unstake',
      'airdrop': '🪂 Airdrop',
      'message_fee': '💬 Message Fee',
      'staking_reward': '💰 Staking Reward',
      'invalid_address': 'Enter a valid 64-character hex address.',
      'positive_amount': 'Enter a positive amount.',
      'sent_success': '✓ Sent!',
      'send_error': 'Error: {error}',
      'hide_qr': '📱 Hide QR Code',
      'show_qr': '📱 Show QR Code',
      'qr_error': 'QR error',
      'address_copied': 'Address copied',
      'nothing_to_copy': 'Nothing to copy',
      'qr_not_ready': 'QR not ready',
      'camera_error': 'Camera error: {error}',
      'address_scanned': '✓ Address scanned',
      'not_valid_wallet_qr': '⚠️ Not a valid wallet QR',
      'fee_label': 'Fee: {fee} BlockCoin',
      'pending_income': 'Pending income: {amount} BlockCoin',
      'apr_label': 'APR: {apr}%',
      'unlock_in': 'unlock in ~{time}',
      'min': 'min',
      'h': 'h',
      'm': 'm'
    };
    let result = fallbacks[key];
    if (result && opts) {
      for (const [k, v] of Object.entries(opts)) {
        result = result.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
      }
    }
    return result || key;
  }

  const MY_ADDRESS = (() => {
    const meta = document.querySelector('meta[name="user-address"]');
    return meta ? meta.content : '';
  })();

  var BLOCKCOIN_SATS = 1_000_000;
  var qrGenerated = false;
  var miningActive = false;
  var POW_MAX_ITERATIONS = 5000000;

  // ================== Майнинг ==================
  async function sha256(text) {
    const encoder = new TextEncoder();
    const data = encoder.encode(text);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }

  async function startMining() {
    if (miningActive) return;
    miningActive = true;

    document.getElementById('startMiningBtn').classList.add('hidden');
    document.getElementById('stopMiningBtn').classList.remove('hidden');
    const statusEl = document.getElementById('miningStatus');
    const progressBar = document.getElementById('miningProgress');
    const fillEl = progressBar.querySelector('.mining-progress-bar-fill');
    progressBar.classList.remove('hidden');
    statusEl.textContent = t('mining_getting_proof');

    try {
      const proofResp = await fetch('/wallet/last-proof');
      const chainData = await proofResp.json();
      let { last_proof, last_index, difficulty, challenge } = chainData;
      const target = '0'.repeat(difficulty);
      const maxIter = POW_MAX_ITERATIONS;

      let startTime = Date.now();
      statusEl.textContent = t('mining_difficulty', { difficulty, tries: Math.floor(maxIter/1000000) });

      while (miningActive) {
        let found = false;
        let proof = 0;
        fillEl.style.width = '0%';

        for (proof = 0; proof < maxIter; proof++) {
          if (!miningActive) break;
          const hash = await sha256(`${last_proof}${challenge}${proof}`);
          if (hash.startsWith(target)) {
            found = true;
            break;
          }
          if (proof % 5000 === 0) {
            const pct = Math.min(100, Math.floor((proof / maxIter) * 100));
            fillEl.style.width = pct + '%';
            if (proof % 50000 === 0) {
              const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
              statusEl.textContent = t('hashing_progress', {
                current: (proof/1000).toFixed(0),
                total: (maxIter/1000).toFixed(0),
                elapsed
              });
            }
            await new Promise(r => setTimeout(r, 0));
          }
        }

        if (found) {
          progressBar.classList.add('hidden');
          statusEl.innerHTML = `<span class="block-found">${t('block_found')}</span>`;
          statusEl.classList.add('block-found-animation');
          setTimeout(() => statusEl.classList.remove('block-found-animation'), 3000);

          try {
            const res = await fetch('/wallet/mine', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ proof, challenge, last_proof, last_index })
            });
            const result = await res.json();

            if (res.ok) {
              const reward = (result.reward / BLOCKCOIN_SATS).toFixed(6);
              statusEl.textContent = t('block_mined', { reward });
              window.NotificationManager?.showToast(t('block_mined_toast', { reward }), 'success');
              refreshBalance();
              refreshNetworkStats();
              loadTx();
              stopMining();
              setTimeout(() => startMining(), 2000);
              return;
            } else if (res.status === 409) {
              const freshResp = await fetch('/wallet/last-proof');
              const freshData = await freshResp.json();
              last_proof = freshData.last_proof;
              last_index = freshData.last_index;
              challenge = freshData.challenge;
              difficulty = freshData.difficulty;
              startTime = Date.now();
              fillEl.style.width = '0%';
              progressBar.classList.remove('hidden');
              continue;
            } else {
              statusEl.textContent = t('error') + ': ' + (result.error || t('unknown'));
              window.NotificationManager?.showToast(t('mining_failed'), 'error');
              stopMining();
              return;
            }
          } catch (err) {
            console.error('Mining POST error:', err);
            statusEl.textContent = t('network_error_submit');
            window.NotificationManager?.showToast(t('network_error'), 'error');
            stopMining();
            return;
          }
        } else {
          statusEl.textContent = t('no_block_restart');
          await new Promise(r => setTimeout(r, 500));
          const fresh = await fetch('/wallet/last-proof');
          const freshData = await fresh.json();
          last_proof = freshData.last_proof;
          last_index = freshData.last_index;
          challenge = freshData.challenge;
          difficulty = freshData.difficulty;
          startTime = Date.now();
        }
      }
    } catch (err) {
      console.error('Mining error:', err);
      statusEl.textContent = t('mining_error', { message: err.message });
      window.NotificationManager?.showToast(t('mining_error_generic'), 'error');
      stopMining();
    }
  }

  function stopMining() {
    miningActive = false;
    document.getElementById('startMiningBtn').classList.remove('hidden');
    document.getElementById('stopMiningBtn').classList.add('hidden');
    document.getElementById('miningProgress').classList.add('hidden');
    document.getElementById('miningStatus').textContent = t('mining_stopped');
  }

  // ================== Стейкинг ==================
  async function stake() {
    const amountEl = document.getElementById('stakeAmount');
    const rawAmount = parseFloat(amountEl.value);
    if (!amountEl.value.trim()) {
      window.NotificationManager?.showToast(t('amount_empty'), 'warning');
      return;
    }
    if (isNaN(rawAmount) || rawAmount <= 0) {
      window.NotificationManager?.showToast(t('invalid_amount'), 'warning');
      return;
    }
    const amount = Math.floor(rawAmount * BLOCKCOIN_SATS);
    const res = await fetch('/wallet/stake', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount })
    });
    const data = await res.json();
    const el = document.getElementById('stakeResult');
    el.classList.remove('hidden');
    if (res.ok) {
      el.textContent = t('staked_success', { block: data.unlock_block });
      el.style.color = 'var(--status-success)';
      amountEl.value = '';
      refreshBalance();
      loadStakingInfo();
    } else {
      el.textContent = t('error') + ': ' + (data.error || t('unknown'));
      el.style.color = 'var(--status-error)';
    }
  }

  async function unstake() {
    const res = await fetch('/wallet/unstake', { method: 'POST' });
    const data = await res.json();
    const el = document.getElementById('stakeResult');
    el.classList.remove('hidden');
    if (res.ok) {
      el.textContent = t('unstaked_success');
      el.style.color = 'var(--status-success)';
      refreshBalance();
      loadStakingInfo();
    } else {
      el.textContent = t('error') + ': ' + (data.error || t('unstake_locked'));
      el.style.color = 'var(--status-error)';
    }
  }

  function estimateTimeFromBlock(unlockBlock, currentBlock) {
    const blocksLeft = unlockBlock - currentBlock;
    const avgBlockTimeSeconds = 60;
    const totalMinutes = Math.max(0, Math.floor((blocksLeft * avgBlockTimeSeconds) / 60));
    if (totalMinutes < 60) return `${totalMinutes} ${t('min')}`;
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    return `${hours}${t('h')} ${mins}${t('m')}`;
  }

  async function loadStakingInfo() {
    const res = await fetch('/wallet/staking/info');
    const data = await res.json();
    const infoEl = document.getElementById('stakingInfo');
    if (data.stakes && data.stakes.length > 0) {
      let html = '';
      const currentBlock = data.current_block || 0;
      let totalStaked = 0;
      let weightedTime = 0;
      const nowSec = Date.now() / 1000;

      data.stakes.forEach(s => {
        totalStaked += s.amount;
        const elapsed = nowSec - s.start_time;
        weightedTime += s.amount * elapsed;
      });

      const avgElapsed = totalStaked > 0 ? weightedTime / totalStaked : 0;
      const years = avgElapsed / (365 * 24 * 3600);
      const apr = years > 0 ? (data.expected_income / totalStaked) / years * 100 : 0;

      data.stakes.forEach(s => {
        const amount = (s.amount / BLOCKCOIN_SATS).toFixed(6);
        const timeEst = estimateTimeFromBlock(s.unlock_block, currentBlock);
        html += `${amount} BlockCoin (${t('unlock_in', { time: timeEst })})<br>`;
      });

      if (data.expected_income) {
        html += `<span style="color: var(--status-success)">${t('pending_income', { amount: (data.expected_income / BLOCKCOIN_SATS).toFixed(6) })}</span><br>`;
      }
      if (totalStaked > 0 && years > 0) {
        html += `<span style="color: var(--accent)">${t('apr_label', { apr: apr.toFixed(2) })}</span>`;
      }
      infoEl.innerHTML = html;
    } else {
      infoEl.textContent = t('no_active_stakes');
    }
  }

  // ================== Баланс ==================
  async function refreshBalance() {
    const res = await fetch('/wallet/balance');
    if (!res.ok) return;
    const data = await res.json();
    document.getElementById('balanceDisplay').textContent = (data.balance / BLOCKCOIN_SATS).toFixed(6) + ' BlockCoin';
    window.NotificationManager?.showToast(t('balance_updated'), 'success');
    if (data.staked) {
      document.getElementById('stakedInfo').style.display = 'flex';
      document.getElementById('stakedDisplay').textContent = (data.staked / BLOCKCOIN_SATS).toFixed(6) + ' BlockCoin';
    } else {
      document.getElementById('stakedInfo').style.display = 'none';
    }
  }

  // ================== Глобальная статистика сети ==================
  async function refreshNetworkStats() {
    try {
      const res = await fetch('/wallet/global-stats');
      if (!res.ok) return;
      const data = await res.json();
      const divisor = data.coin_divisor;
      if (data.remaining_supply !== null) {
        document.getElementById('remainingSupply').textContent = (data.remaining_supply / divisor).toFixed(6) + ' ' + data.coin_name;
        document.getElementById('remainingRow').style.display = '';
      } else {
        document.getElementById('remainingSupply').textContent = '∞';
        document.getElementById('remainingRow').style.display = 'none';
      }
      document.getElementById('totalSupply').textContent = (data.total_supply / divisor).toFixed(6) + ' ' + data.coin_name;
      document.getElementById('stakingPoolBalance').textContent = (data.staking_pool_balance / divisor).toFixed(6) + ' ' + data.coin_name;
      document.getElementById('messageFee').textContent = (data.message_fee / divisor).toFixed(6) + ' ' + data.coin_name;
      document.getElementById('blockReward').textContent = (data.block_reward / divisor).toFixed(6) + ' ' + data.coin_name;
      document.getElementById('totalBlocks').textContent = data.total_blocks;
      document.getElementById('totalStaked').textContent = (data.total_staked / divisor).toFixed(6) + ' ' + data.coin_name;
      document.getElementById('difficulty').textContent = data.difficulty;
      window.NotificationManager?.showToast(t('network_stats_updated'), 'success');
    } catch (err) {
      console.error('Failed to load network stats:', err);
    }
  }

  // ================== Транзакции ==================
  async function loadTx() {
    const list = document.getElementById('txList');
    list.innerHTML = '<div class="loading">' + t('loading') + '</div>';
    const res = await fetch('/wallet/transactions');
    if (!res.ok) {
      list.innerHTML = '<p class="text-muted text-center">' + t('failed_to_load') + '</p>';
      return;
    }
    const data = await res.json();
    if (!data.transactions.length) {
      list.innerHTML = `<div class="empty-state"><div class="icon">💳</div><p>${t('no_transactions')}</p></div>`;
      return;
    }
    while (list.firstChild) list.removeChild(list.firstChild);

    data.transactions.forEach(tx => {
      const item = document.createElement('div');
      item.className = 'list-item';

      let typeLabel = '';
      let sign = '-';
      if (tx.type === 'reward') {
        typeLabel = t('lottery_reward');
        sign = '+';
      } else if (tx.type === 'fee') {
        typeLabel = t('fee');
        sign = '-';
      } else if (tx.type === 'transfer') {
        if (tx.sender === MY_ADDRESS) {
          typeLabel = t('sent');
          sign = '-';
        } else {
          typeLabel = t('received');
          sign = '+';
        }
      } else if (tx.type === 'block_reward') {
        typeLabel = t('block_reward');
        sign = '+';
      } else if (tx.type === 'stake') {
        typeLabel = t('stake_label');
        sign = '-';
      } else if (tx.type === 'unstake') {
        typeLabel = t('unstake_label');
        sign = '+';
      } else if (tx.type === 'airdrop') {
        typeLabel = t('airdrop');
        sign = '+';
      } else if (tx.type === 'message_fee') {
        typeLabel = t('message_fee');
        sign = '-';
      } else if (tx.type === 'staking_reward') {
        typeLabel = t('staking_reward');
        sign = '+';
      }

      const amount = (tx.amount / BLOCKCOIN_SATS).toFixed(6);
      const timestamp = tx.timestamp ? new Date(tx.timestamp * 1000).toLocaleString() : '';

      const infoDiv = document.createElement('div');
      infoDiv.className = 'info';
      const nameDiv = document.createElement('div');
      nameDiv.className = 'name';
      nameDiv.textContent = typeLabel;
      const timeDiv = document.createElement('div');
      timeDiv.className = 'address font-mono text-muted';
      timeDiv.style.fontSize = '10px';
      timeDiv.textContent = timestamp;
      infoDiv.appendChild(nameDiv);
      infoDiv.appendChild(timeDiv);

      const actionsDiv = document.createElement('div');
      actionsDiv.className = 'actions';
      const amountSpan = document.createElement('span');
      amountSpan.style.fontWeight = '600';
      amountSpan.style.color = sign === '+' ? 'var(--status-success)' : 'var(--status-warning)';
      amountSpan.textContent = `${sign}${amount} BlockCoin`;
      actionsDiv.appendChild(amountSpan);

      item.appendChild(infoDiv);
      item.appendChild(actionsDiv);
      list.appendChild(item);
    });
  }

  async function sendCoins() {
    const addr = document.getElementById('sendAddress').value.trim().toLowerCase();
    const rawAmount = Number(document.getElementById('sendAmount').value);
    if (!addr || addr.length !== 64 || !/^[a-f0-9]{64}$/.test(addr)) {
      window.NotificationManager?.showToast(t('invalid_address'), 'warning');
      return;
    }
    if (isNaN(rawAmount) || rawAmount <= 0) {
      window.NotificationManager?.showToast(t('positive_amount'), 'warning');
      return;
    }
    const amount = Math.floor(rawAmount * BLOCKCOIN_SATS);
    const res = await fetch('/wallet/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recipient: addr, amount })
    });
    const result = await res.json();
    const el = document.getElementById('sendResult');
    el.classList.remove('hidden');
    if (res.ok) {
      el.textContent = t('sent_success');
      el.style.color = 'var(--status-success)';
      document.getElementById('sendAmount').value = '';
      document.getElementById('sendAddress').value = '';
      refreshBalance();
      loadTx();
    } else {
      el.textContent = t('send_error', { error: result.error });
      el.style.color = 'var(--status-error)';
    }
  }

  // ================== QR-код и сканер ==================
  function toggleReceiveQR() {
    const block = document.getElementById('qrBlock');
    const btn = document.getElementById('toggleQRBtn');
    if (!block || !btn) return;

    const isHidden = block.classList.contains('hidden');
    if (isHidden) {
      block.classList.remove('hidden');
      if (!qrGenerated) generateQR();
      btn.innerHTML = t('hide_qr');
    } else {
      block.classList.add('hidden');
      btn.innerHTML = t('show_qr');
    }
  }

  function generateQR() {
    const address = MY_ADDRESS;
    const qrDiv = document.getElementById('qrcode');
    if (!address || address === 'None' || !qrDiv || typeof QRCode === 'undefined') return;
    qrDiv.innerHTML = '';
    try {
      new QRCode(qrDiv, {
        text: address,
        width: 220, height: 220,
        colorDark: getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff',
        colorLight: getComputedStyle(document.documentElement).getPropertyValue('--bg-primary').trim() || '#0a0a0a',
        correctLevel: QRCode.CorrectLevel.H
      });
      qrGenerated = true;
    } catch (e) {
      qrDiv.innerHTML = '<span class="text-muted">' + t('qr_error') + '</span>';
    }
  }

  function copyAddressToClipboard() {
    const addr = document.getElementById('receiveAddress')?.textContent?.trim();
    copyToClipboard(addr, t('address_copied'), t('nothing_to_copy'));
  }

  function downloadQR() {
    const canvas = document.querySelector('#qrcode canvas');
    if (!canvas) return window.NotificationManager?.showToast(t('qr_not_ready'), 'error');
    const link = document.createElement('a');
    link.download = `wallet-qr-${Date.now()}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }

  async function shareQR() {
    const address = document.getElementById('receiveAddress')?.textContent?.trim();
    if (!address) return;
    if (navigator.share) {
      try {
        await navigator.share({ title: t('my_wallet_address'), text: address });
      } catch (e) { if (e.name !== 'AbortError') console.error(e); }
    } else {
      copyAddressToClipboard();
    }
  }

  async function copyToClipboard(text, successMsg, errorMsg) {
    if (!text) return window.NotificationManager?.showToast(errorMsg, 'error');
    try {
      await navigator.clipboard.writeText(text);
      window.NotificationManager?.showToast(successMsg, 'success');
    } catch {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select(); document.execCommand('copy');
        document.body.removeChild(ta);
        window.NotificationManager?.showToast(successMsg, 'success');
      } catch (e) {
        window.NotificationManager?.showToast(errorMsg, 'error');
      }
    }
  }

  // ================== QR-сканер (wallet) ==================
  var walletQR = {
    stream: null,
    active: false,
    animationFrame: null,
    canvas: null,
    ctx: null,
    config: {
      videoWidth: 1280,
      videoHeight: 720,
      scanSize: 400,
      inversionAttempts: "attemptBoth",
      scanInterval: 100
    },
    open() {
      if (this.active) return;
      const video = document.getElementById('qrVideo');
      const container = document.getElementById('qrScannerContainer');
      const resultEl = document.getElementById('scanResult');
      if (!video || !container) return;
      this.active = true;
      container.classList.remove('hidden');
      resultEl?.classList.add('hidden');
      resultEl && (resultEl.textContent = '');

      navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: this.config.videoWidth }, height: { ideal: this.config.videoHeight } },
        audio: false
      }).then(stream => {
        if (!this.active) return this._stopStream(stream);
        this.stream = stream;
        video.srcObject = stream;
        return video.play();
      }).then(() => {
        const wait = () => {
          if (!this.active) return;
          if (video.videoWidth > 0 && video.videoHeight > 0) {
            this._startScanning(video, resultEl);
          } else {
            setTimeout(wait, 50);
          }
        };
        wait();
      }).catch(err => {
        this._showError(t('camera_error', { error: err.message || err.name }), resultEl);
      });
    },
    close() {
      this.active = false;
      if (this.animationFrame) cancelAnimationFrame(this.animationFrame);
      if (this.stream) this._stopStream(this.stream);
      document.getElementById('qrScannerContainer')?.classList.add('hidden');
    },
    _stopStream(stream) {
      stream?.getTracks().forEach(t => t.stop());
    },
    _showError(msg, resultEl) {
      if (resultEl) { resultEl.textContent = '⚠️ ' + msg; resultEl.style.color = 'var(--status-error)'; resultEl.classList.remove('hidden'); }
      setTimeout(() => this.close(), 3000);
    },
    _startScanning(video, resultEl) {
      if (!this.active) return;
      if (!this.canvas) {
        this.canvas = document.createElement('canvas');
        this.canvas.width = this.config.scanSize;
        this.canvas.height = this.config.scanSize;
        this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
      }
      let lastScan = 0;
      const scan = () => {
        if (!this.active) return;
        const now = performance.now();
        if (now - lastScan < this.config.scanInterval) {
          this.animationFrame = requestAnimationFrame(scan);
          return;
        }
        lastScan = now;
        if (video.readyState !== video.HAVE_ENOUGH_DATA || !video.videoWidth) {
          this.animationFrame = requestAnimationFrame(scan);
          return;
        }
        try {
          const vw = video.videoWidth, vh = video.videoHeight;
          const size = Math.min(vw, vh) * 0.8;
          const sx = (vw - size) / 2, sy = (vh - size) / 2;
          const ctx = this.ctx;
          const canvas = this.canvas;
          canvas.width = this.config.scanSize;
          canvas.height = this.config.scanSize;
          ctx.drawImage(video, sx, sy, size, size, 0, 0, this.config.scanSize, this.config.scanSize);
          const imageData = ctx.getImageData(0, 0, this.config.scanSize, this.config.scanSize);
          const code = jsQR(imageData.data, this.config.scanSize, this.config.scanSize, { inversionAttempts: this.config.inversionAttempts });
          if (code?.data) {
            const addr = parseQRData(code.data);
            if (addr) {
              document.getElementById('sendAddress').value = addr;
              if (resultEl) { resultEl.textContent = t('address_scanned'); resultEl.style.color = 'var(--status-success)'; resultEl.classList.remove('hidden'); }
              this.close();
              return;
            } else {
              if (resultEl) { resultEl.textContent = t('not_valid_wallet_qr'); resultEl.style.color = 'var(--status-warning)'; resultEl.classList.remove('hidden'); }
            }
          }
        } catch (e) { /* ignore */ }
        if (this.active) this.animationFrame = requestAnimationFrame(scan);
      };
      this.animationFrame = requestAnimationFrame(scan);
    }
  };

  function parseQRData(data) {
    if (!data) return null;
    if (/^[a-fA-F0-9]{64}$/.test(data)) return data.toLowerCase();
    const match = data.match(/(?:darkmsg|bitcoin):([a-fA-F0-9]{64})/i);
    if (match?.[1]) return match[1].toLowerCase();
    return null;
  }

  function openWalletQRScanner() { walletQR.open(); }
  function forceCloseWalletQRScanner() { walletQR.close(); }

  // ================== Уведомления о новых блоках через WebSocket ==================
  function initMiningNotifications() {
    if (!window.wsClient) {
      console.warn('WebSocket client not ready, mining notifications disabled');
      const checkInterval = setInterval(() => {
        if (window.wsClient) {
          clearInterval(checkInterval);
          attachListener();
        }
      }, 500);
      setTimeout(() => clearInterval(checkInterval), 10000);
      return;
    }
    attachListener();

    function attachListener() {
      if (!window.wsClient) return;
      const originalOnMessage = window.wsClient.onMessage;
      window.wsClient.onMessage = (data) => {
        if (originalOnMessage) originalOnMessage(data);
        if (data.type === 'new_block' && miningActive) {
          console.log('🔔 New block mined, restarting mining...');
          refreshNetworkStats();
          refreshBalance();
          const wasActive = miningActive;
          stopMining();
          if (wasActive) {
            setTimeout(() => startMining(), 500);
          }
        }
      };
      console.log('Mining notifications enabled');
    }
  }

  // ================== Инициализация ==================
  document.addEventListener('DOMContentLoaded', function() {
    fetch('/wallet/config')
      .then(r => r.json())
      .then(cfg => {
        POW_MAX_ITERATIONS = cfg.pow_max_iterations || 5000000;
        if (!cfg.enable_mining) document.getElementById('miningCard')?.remove();
        if (!cfg.enable_staking) document.getElementById('stakingCard')?.remove();
        window.refreshFeeDisplay();
      })
      .catch(e => console.error('Error fetching wallet config:', e));

    refreshBalance();
    loadTx();
    loadStakingInfo();
    refreshNetworkStats();
    initMiningNotifications();
  });
// ================== Обновление отображения комиссии ==================
window.refreshFeeDisplay = async function() {
    try {
        const res = await fetch('/wallet/config');
        if (!res.ok) throw new Error('Config not loaded');
        const cfg = await res.json();
        const feeDisplay = document.getElementById('sendFeeDisplay');
        if (feeDisplay) {
            const fee = (cfg.transfer_fee / BLOCKCOIN_SATS).toFixed(6);
            feeDisplay.textContent = t('fee_label', { fee });
        }
    } catch(e) {
        console.warn('Failed to refresh fee display', e);
        // fallback на случай ошибки
        const feeDisplay = document.getElementById('sendFeeDisplay');
        if (feeDisplay) feeDisplay.textContent = t('fee_label', { fee: '0.010000' });
    }
};

  window.startMining = startMining;
  window.stopMining = stopMining;
  window.stake = stake;
  window.unstake = unstake;
  window.sendCoins = sendCoins;
  window.toggleReceiveQR = toggleReceiveQR;
  window.copyAddressToClipboard = copyAddressToClipboard;
  window.downloadQR = downloadQR;
  window.shareQR = shareQR;
  window.openWalletQRScanner = openWalletQRScanner;
  window.forceCloseWalletQRScanner = forceCloseWalletQRScanner;
  window.refreshBalance = refreshBalance;
  window.refreshNetworkStats = refreshNetworkStats;
})();