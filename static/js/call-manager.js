/**
 * call-manager.js — WebRTC менеджер с iOS-фиксами, таймером разговора и полной i18n поддержкой
 * Исправлено: добавлен флаг isEstablishing для защиты от восстановления во время запроса микрофона
 */
(function() {
    if (window.CallManagerLoaded) return;
    window.CallManagerLoaded = true;

    class CallManager {
        constructor() {
    this.pc = null;
    this.localStream = null;
    this.currentCallId = null;
    this.currentPartner = null;
    this.currentPartnerName = null;
    this.isInitiator = false;
    this.isAudioOnly = true;
    this.iceServers = [];
    this.isMuted = false;
    this.isSpeakerEnabled = false;
    this.activeModal = null;
    this.remoteAudio = null;
    this.isCompactMode = false;
    this.isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
    this.outsideClickListener = null;
    this.audioCtx = null;
    this._visibilityHandler = null;
    this._incomingModalObserver = null;   // ← ДОБАВИТЬ ЭТУ СТРОКУ

    // FIX: буфер для ICE candidates
    this.pendingCandidates = [];
    this.pendingAnswer = null;

    // Таймер разговора
    this.callStartTime = null;
    this.callDurationInterval = null;

    // Флаг: соединение в процессе установки
    this.isEstablishing = false;
    this._disconnectTimer = null;
    this._connectTimeout = null;



}

        t(key, defaultValue = '') {
            if (typeof i18next !== 'undefined' && i18next.isInitialized && i18next.exists(key)) {
                return i18next.t(key);
            }
            const fallback = {
                'call_calling': 'Calling...',
                'call_connected': 'Connected',
                'call_connecting': 'Connecting...',
                'call_accept': 'Accept',
                'call_reject': 'Reject',
                'call_end': 'End call',
                'call_mute_microphone': 'Mute microphone',
                'call_unmute_microphone': 'Unmute microphone',
                'call_speaker': 'Speaker',
                'call_earpiece': 'Earpiece',
                'call_minimize': 'Minimize',
                'call_expand': 'Expand',
                'call_from': 'from',
                'incoming_call': 'Incoming call',
                'call_ended': 'Call ended',
                'call_rejected': 'Call rejected'
            };
            return fallback[key] || defaultValue || key;
        }

        formatDuration(ms) {
            const totalSeconds = Math.floor(ms / 1000);
            const hours = Math.floor(totalSeconds / 3600);
            const minutes = Math.floor((totalSeconds % 3600) / 60);
            const seconds = totalSeconds % 60;
            if (hours > 0) {
                return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            }
            return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }

        updateDurationDisplay() {
            if (!this.callStartTime) {
                this.setDurationText('00:00');
                return;
            }
            const elapsed = Date.now() - this.callStartTime;
            const formatted = this.formatDuration(elapsed);
            this.setDurationText(formatted);
        }

        setDurationText(text) {
            const durationElem = document.getElementById('callDuration');
            if (durationElem) durationElem.textContent = text;
            const miniDurationElem = document.getElementById('miniDuration');
            if (miniDurationElem) miniDurationElem.textContent = text;
        }

        startCallTimer() {
            if (this.callDurationInterval) clearInterval(this.callDurationInterval);
            this.callStartTime = Date.now();
            this.updateDurationDisplay();
            this.callDurationInterval = setInterval(() => this.updateDurationDisplay(), 1000);
        }

        stopCallTimer() {
            if (this.callDurationInterval) {
                clearInterval(this.callDurationInterval);
                this.callDurationInterval = null;
            }
            this.callStartTime = null;
            this.setDurationText('00:00');
        }

        async init() {
            try {
                const res = await fetch('/calls/turn-credentials');
                const data = await res.json();
                this.iceServers = data.iceServers;
                console.log('ICE servers loaded', this.iceServers);
                if ("Notification" in window && Notification.permission === "default") {
                     await Notification.requestPermission();
                }

            } catch(e) {
                console.warn('Failed to load TURN config, fallback to STUN only', e);
                this.iceServers = [{ urls: 'stun:stun.l.google.com:19302' }];
            }

            this.remoteAudio = document.createElement('audio');
            this.remoteAudio.id = 'remoteAudio';
            this.remoteAudio.autoplay = true;
            this.remoteAudio.setAttribute('playsinline', '');
            this.remoteAudio.style.position = 'absolute';
            this.remoteAudio.style.visibility = 'hidden';
            document.body.appendChild(this.remoteAudio);

            if (this.isIOS) {
                const unlockGesture = async () => {
                    if (this.remoteAudio) {
                        await this.remoteAudio.play().catch(() => {});
                        await this.unlockAudioContext();
                    }
                    document.removeEventListener('touchstart', unlockGesture);
                    document.removeEventListener('click', unlockGesture);
                };
                document.addEventListener('touchstart', unlockGesture, { once: true });
                document.addEventListener('click', unlockGesture, { once: true });
            }

            this._visibilityHandler = () => {
                if (document.visibilityState !== 'visible') return;
                if (!this.pc) return;
                if (this.isEstablishing) {
                    console.log('[CallManager] Skipping visibility recovery – call is establishing');
                    return;
                }
                const state = this.pc.connectionState;
                const ice = this.pc.iceConnectionState;

                if (state === 'failed' || state === 'closed' || ice === 'failed' || ice === 'disconnected') {
                    console.warn('[CallManager] Recovery: restarting call due to state', { state, ice });
                    this.restartCallFull();
                } else {
                    this.reattachRemoteStream();
                    if (ice !== 'connected' && ice !== 'completed') {
                        this.restartIce();
                    }
                }
            };
            document.addEventListener('visibilitychange', this._visibilityHandler);

            if (typeof i18next !== 'undefined' && i18next.isInitialized) {
                this.createMiniWidget();
                this.updateLocalizedTexts();
            } else {
                document.addEventListener('i18next:initialized', () => {
                    this.createMiniWidget();
                    this.updateLocalizedTexts();
                }, { once: true });
            }
        }

        unlockAudioContext() {
            if (!this.isIOS) return Promise.resolve();
            if (this.audioCtx && this.audioCtx.state === 'running') return Promise.resolve();
            try {
                this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                const buf = this.audioCtx.createBuffer(1, 1, 22050);
                const src = this.audioCtx.createBufferSource();
                src.buffer = buf;
                src.connect(this.audioCtx.destination);
                src.start(0);
                return this.audioCtx.resume();
            } catch(e) {
                console.warn('[iOS] AudioContext unlock failed:', e);
                return Promise.resolve();
            }
        }

        playIncomingSound() {
    if (this._incomingAudio) return;
    // Сначала пробуем разблокировать аудиоконтекст (если ещё не был)
    this.unlockAudioContext().then(() => {
        try {
            const audio = new Audio("/sounds/incoming.mp3");
            audio.loop = true;
            audio.volume = 0.8;
            const playPromise = audio.play();
            if (playPromise !== undefined) {
                playPromise.catch(err => console.warn("[CallManager] sound blocked:", err));
            }
            this._incomingAudio = audio;
        } catch (e) {
            console.warn("incoming sound error", e);
        }
    }).catch(() => {});
}

        stopIncomingSound() {
            if (this._incomingAudio) {
                this._incomingAudio.pause();
                this._incomingAudio.currentTime = 0;
                this._incomingAudio = null;
            }
        }

        reattachRemoteStream() {
            if (!this.remoteAudio || !window._remoteStream) return;
            this.remoteAudio.srcObject = null;
            this.remoteAudio.srcObject = window._remoteStream;
            this.remoteAudio.play().catch(e => console.warn('[iOS] play() after reattach failed:', e));
        }

        flushPendingCandidates() {
            if (!this.pc) return;
            console.log('[ICE] Flushing', this.pendingCandidates.length, 'buffered candidates');
            for (const candidate of this.pendingCandidates) {
                this.pc.addIceCandidate(new RTCIceCandidate(candidate))
                    .then(() => console.log('[ICE] Buffered candidate added OK'))
                    .catch(err => console.warn('[ICE] Failed to add buffered candidate:', err));
            }
            this.pendingCandidates = [];
        }

        async restartIce() {
            if (!this.pc || !this.currentPartner) return;
            if (this.isIOS) {
                console.warn('[CallManager] ICE restart disabled on iOS');
                this.endCall();
                return;
            }
            try {
                const offer = await this.pc.createOffer({ iceRestart: true });
                offer.sdp = this.preferOpusCodec(offer.sdp);
                await this.pc.setLocalDescription(offer);
                window.wsClient?.send({
                    type: 'call_offer',
                    target: this.currentPartner,
                    call_id: this.currentCallId,
                    sdp: offer,
                    is_restart: true
                });
                console.log('[CallManager] ICE restart offer sent');
            } catch(e) {
                console.error('[CallManager] ICE restart failed:', e);
                this.endCall();
            }
        }

        async restartCallFull() {
            if (!this.currentPartner || !this.currentCallId) return;
            if (!this.isInitiator) {
                console.warn('[CallManager] Incoming call lost after sleep – ending call');
                this.endCall();
                window.NotificationManager?.showToast('Call lost due to connection timeout', 'error');
                return;
            }
            const partner = this.currentPartner;
            const isAudioOnly = this.isAudioOnly;
            const partnerName = this.currentPartnerName;
            console.log('[CallManager] FULL RESTART CALL', this.currentCallId);
            this.endCall();
            await new Promise(resolve => setTimeout(resolve, 300));
            await this.makeCall(partner, !isAudioOnly, partnerName);
        }

        preferOpusCodec(sdp) {
            if (this.isIOS) return sdp;
            if (!sdp) return sdp;
            const lines = sdp.split('\r\n');
            const mIdx = lines.findIndex(l => l.startsWith('m=audio'));
            if (mIdx === -1) return sdp;
            const opusLine = lines.find(l => /opus\/48000/i.test(l));
            if (!opusLine) return sdp;
            const payload = opusLine.match(/:(\d+)/)?.[1];
            if (!payload) return sdp;
            lines[mIdx] = lines[mIdx].replace(
                /^(m=audio \d+ \S+)(.*)/,
                (_, prefix, rest) => {
                    const payloads = rest.trim().split(' ').filter(p => p !== payload);
                    return `${prefix} ${payload} ${payloads.join(' ')}`;
                }
            );
            return lines.join('\r\n');
        }

        createMiniWidget() {
            if (document.getElementById('callMiniWidget')) return;
            const widget = document.createElement('div');
            widget.id = 'callMiniWidget';
            widget.className = 'call-mini-widget hidden';
            widget.innerHTML = `
                <div class="call-mini-avatar" id="miniAvatar">📞</div>
                <div class="call-mini-info">
                    <div class="call-mini-name" id="miniName">Call</div>
                    <div class="call-mini-status" id="miniStatus"></div>
                    <div class="call-mini-duration" id="miniDuration" style="font-size: 11px; color: var(--text-muted);">00:00</div>
                </div>
                <div class="call-mini-actions">
                    <button class="call-mini-btn" id="miniExpandBtn">⤢</button>
                    <button class="call-mini-btn call-mini-end" id="miniEndBtn">📞</button>
                </div>
            `;
            document.body.appendChild(widget);
            document.getElementById('miniExpandBtn')?.addEventListener('click', (e) => {
                e.stopPropagation();
                this.expandFromMini();
            });
            document.getElementById('miniEndBtn')?.addEventListener('click', (e) => {
                e.stopPropagation();
                this.endCall();
            });
            widget.addEventListener('click', (e) => {
                if (e.target.closest('.call-mini-btn')) return;
                if (this.isCompactMode) this.expandFromMini();
            });

            let isDragging = false, startX, startY, offsetX, offsetY;
            const onDragStart = (e, clientX, clientY) => {
                if (e.target.closest('.call-mini-btn')) return;
                isDragging = true;
                startX = clientX; startY = clientY;
                const rect = widget.getBoundingClientRect();
                offsetX = startX - rect.left;
                offsetY = startY - rect.top;
                widget.style.cursor = 'grabbing';
                e.preventDefault();
            };
            const onDragMove = (clientX, clientY) => {
                if (!isDragging) return;
                let left = Math.min(Math.max(clientX - offsetX, 8), window.innerWidth - widget.offsetWidth - 8);
                let top  = Math.min(Math.max(clientY - offsetY, 8), window.innerHeight - widget.offsetHeight - 8);
                widget.style.left = left + 'px';
                widget.style.top = top + 'px';
                widget.style.right = 'auto';
                widget.style.bottom = 'auto';
            };
            const onDragEnd = () => {
                isDragging = false;
                widget.style.cursor = 'grab';
            };
            widget.addEventListener('mousedown', (e) => onDragStart(e, e.clientX, e.clientY));
            document.addEventListener('mousemove', (e) => onDragMove(e.clientX, e.clientY));
            document.addEventListener('mouseup', onDragEnd);
            widget.addEventListener('touchstart', (e) => {
                const t = e.touches[0];
                onDragStart(e, t.clientX, t.clientY);
            }, { passive: false });
            document.addEventListener('touchmove', (e) => {
                if (!isDragging) return;
                const t = e.touches[0];
                onDragMove(t.clientX, t.clientY);
                e.preventDefault();
            }, { passive: false });
            document.addEventListener('touchend', onDragEnd);
        }

        addOutsideClickListener() {
            this.removeOutsideClickListener();
            const attachAfterDelay = () => {
                this.outsideClickListener = (e) => {
                    const modal = document.getElementById('callModal');
                    if (!modal || modal.classList.contains('hidden')) return;
                    if (e.target.closest('#callCollapseBtn')) return;
                    if (e.target.closest('#callMiniWidget')) return;
                    if (!e.target.closest('.modal')) {
                        this.collapseToMini();
                    }
                };
                document.addEventListener('click', this.outsideClickListener);
                document.addEventListener('touchstart', this.outsideClickListener);
            };
            setTimeout(attachAfterDelay, 400);
        }

        removeOutsideClickListener() {
            if (this.outsideClickListener) {
                document.removeEventListener('click', this.outsideClickListener);
                document.removeEventListener('touchstart', this.outsideClickListener);
                this.outsideClickListener = null;
            }
        }

        async getUserMedia() {
            if (this.localStream) {
                const tracks = this.localStream.getTracks();
                const allLive = tracks.length > 0 && tracks.every(t => t.readyState === 'live');
                if (!allLive) {
                    console.warn('[CallManager] Cached localStream has dead tracks, requesting new');
                    this.localStream.getTracks().forEach(t => t.stop());
                    this.localStream = null;
                }
            }
            if (this.localStream) return this.localStream;
            try {
                this.localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: !this.isAudioOnly });
                return this.localStream;
            } catch(e) {
                console.error('Media access denied', e);
                throw new Error('Cannot access microphone/camera');
            }
        }

        closeMedia() {
            if (this.localStream) {
                this.localStream.getTracks().forEach(t => t.stop());
                this.localStream = null;
            }
            if (this.remoteAudio?.srcObject) {
                this.remoteAudio.srcObject.getTracks().forEach(t => t.stop());
                this.remoteAudio.srcObject = null;
            }
            if (window._remoteStream) {
                window._remoteStream.getTracks().forEach(t => t.stop());
                window._remoteStream = null;
            }
        }

        async makeCall(partnerAddress, isVideo = false, partnerName = '') {
            // Проверка: если уже есть активный звонок
            if (this.currentCallId) {
                const confirmEnd = confirm(this.t('call_active_message', 'You are already in a call. End it to start a new one?'));
                if (!confirmEnd) {
                    window.NotificationManager?.showToast(this.t('call_in_progress', 'Call already in progress'), 'warning');
                    return;
                }
                this.endCall();
                await new Promise(r => setTimeout(r, 500));
            }

            await this.unlockAudioContext();

            this.isEstablishing = true;
            try {
                this.isAudioOnly = !isVideo;
                this.currentPartner = partnerAddress;
                this.currentPartnerName = partnerName || partnerAddress.slice(0,10) + '…';
                this.isInitiator = true;
                this.currentCallId = `call_${Date.now()}_${Math.random().toString(36)}`;

                const stream = await this.getUserMedia();
                this.createPeerConnection();
                stream.getTracks().forEach(track => this.pc.addTrack(track, stream));

                const offer = await this.pc.createOffer();
                offer.sdp = this.preferOpusCodec(offer.sdp);
                await this.pc.setLocalDescription(offer);
                this.flushPendingAnswer();

                // Отправляем offer через WebSocket
                window.wsClient?.send({
                    type: 'call_offer',
                    target: partnerAddress,
                    call_id: this.currentCallId,
                    sdp: offer
                    // ИСПРАВЛЕНИЕ: УБРАН from_name!
                    // Раньше тут было from_name: this.currentPartnerName,
                    // что отправляло имя того, КОМУ мы звоним (Боба).
                    // Теперь сервер сам подставит правильное имя звонящего (Алисы).
                });

                this.showCallModal('outgoing', this.t('call_calling'));
            } catch(err) {
                console.error(err);
                this.endCall();
                window.NotificationManager?.showToast('Cannot start call: ' + err.message, 'error');
            } finally {
                setTimeout(() => { if (this.isEstablishing) this.isEstablishing = false; }, 5000);
            }
        }

        createPeerConnection() {
            if (this.pc) {
                this.pc.onconnectionstatechange = null;
                this.pc.oniceconnectionstatechange = null;
                this.pc.onicecandidate = null;
                this.pc.ontrack = null;
                this.pc.close();
                this.stopCallTimer();
            }
            this.pendingCandidates = [];
            this.pendingAnswer = null;
            window._remoteStream = null;
            if (window._pendingCallHandled) window._pendingCallHandled = false;
            this.pc = new RTCPeerConnection({ iceServers: this.iceServers });

            this.pc.onicecandidate = (event) => {
                if (event.candidate && this.currentPartner) {
                    console.log('[ICE] Sending candidate to', this.currentPartner.slice(0,10), ':', event.candidate.candidate?.split(' ')[7]);
                    window.wsClient?.send({
                        type: 'call_ice',
                        target: this.currentPartner,
                        call_id: this.currentCallId,
                        candidate: event.candidate
                    });
                } else if (!event.candidate) {
                    console.log('[ICE] Gathering complete (null candidate)');
                }
            };

            this.pc.onicegatheringstatechange = () => {
                console.log('[ICE] Gathering state:', this.pc.iceGatheringState);
            };

            this.pc.ontrack = (event) => {
                window._remoteStream = event.streams[0] || (event.track && new MediaStream([event.track]));
                if (this.remoteAudio) {
                    this.remoteAudio.srcObject = null;
                    this.remoteAudio.srcObject = window._remoteStream;
                    this.remoteAudio.muted = true;
                    this.remoteAudio.play()
                        .then(() => { if (this.remoteAudio) this.remoteAudio.muted = false; })
                        .catch(e => { console.warn('Audio play failed:', e); if (this.remoteAudio) this.remoteAudio.muted = false; });
                }
                this.attachRemoteStream(window._remoteStream);
                this.updateCallStatus('connected');
            };

            this.pc.onconnectionstatechange = () => {
                const s = this.pc.connectionState;
                console.log('[CallManager] connection state:', s, '| ICE:', this.pc.iceConnectionState, '| gathering:', this.pc.iceGatheringState);
                if (s === 'failed' || s === 'closed') {
                    this.endCall();
                } else if (s === 'connecting' || s === 'new') {
                    this.updateCallStatus('connecting');
                } else if (s === 'connected') {
                    if (this._connectTimeout) { clearTimeout(this._connectTimeout); this._connectTimeout = null; }
                    this.isEstablishing = false;
                    const callModal = document.getElementById('callModal');
                    if (callModal && callModal.classList.contains('hidden') && !this.isCompactMode) {
                        this.showCallModal('active', this.t('call_connected'));
                    } else {
                        this.updateCallStatus('connected');
                    }
                    if (!this.callStartTime) this.startCallTimer();
                }
            };

            this.pc.oniceconnectionstatechange = () => {
                const s = this.pc.iceConnectionState;
                console.log('[CallManager] ICE state:', s);
                if (s === 'failed') {
                    if (this.isIOS) {
                        console.warn('[CallManager] ICE failed on iOS, ending call');
                        this.endCall();
                    } else {
                        if (this.currentPartner && this.currentCallId) {
                            console.warn('[CallManager] ICE failed, attempting restart');
                            this.restartIce();
                        } else {
                            this.endCall();
                        }
                    }
                } else if (s === 'disconnected') {
                    if (this._disconnectTimer) clearTimeout(this._disconnectTimer);
                    this._disconnectTimer = setTimeout(() => {
                        if (this.isEstablishing) {
                            console.log('[CallManager] Skipping disconnect recovery – call is establishing');
                            return;
                        }
                        if (this.pc && this.pc.iceConnectionState === 'disconnected' && this.currentPartner) {
                            console.warn('[CallManager] ICE disconnected too long, restarting call');
                            this.restartCallFull();
                        }
                    }, 10000);
                } else if (s === 'connected' || s === 'completed') {
                    if (this._disconnectTimer) {
                        clearTimeout(this._disconnectTimer);
                        this._disconnectTimer = null;
                    }
                }
            };

            if (this._connectTimeout) clearTimeout(this._connectTimeout);
            this._connectTimeout = setTimeout(() => {
                if (this.pc && this.pc.connectionState !== 'connected') {
                    console.error('[CallManager] Connection timeout');
                    window.NotificationManager?.showToast('Call failed: connection timeout', 'error');
                    this.endCall();
                }
            }, 30000);
        }

        attachRemoteStream(stream) {
            const remoteVideo = document.getElementById('remoteVideo');
            if (remoteVideo && stream.getVideoTracks().length > 0) {
                remoteVideo.srcObject = stream;
                remoteVideo.play().catch(e => console.warn);
            }
        }

        async answerCall(callId, fromAddress, offerSdp, partnerName = '') {
            console.log('[answerCall] start, callId:', callId, 'from:', fromAddress);
            this.stopIncomingSound();
            await this.unlockAudioContext();

            this.isEstablishing = true;
            try {
                this.currentCallId = callId;
                this.currentPartner = fromAddress;
                this.currentPartnerName = partnerName || fromAddress.slice(0,10) + '…';
                this.isInitiator = false;

                let offer = offerSdp;
                if (typeof offerSdp === 'string') {
                    try { offer = JSON.parse(offerSdp); } catch(e) { offer = offerSdp; }
                }
                if (!offer || !offer.sdp) {
                    console.error('[answerCall] Invalid or missing offerSdp:', offerSdp);
                    window.NotificationManager?.showToast('Call failed: missing offer SDP', 'error');
                    return;
                }

                const stream = await this.getUserMedia();
                this.createPeerConnection();
                stream.getTracks().forEach(track => this.pc.addTrack(track, stream));
                this.showCallModal('active', this.t('call_connecting'));

                await this.pc.setRemoteDescription(new RTCSessionDescription(offer));
                this.flushPendingCandidates();

                const answer = await this.pc.createAnswer();
                answer.sdp = this.preferOpusCodec(answer.sdp);
                await this.pc.setLocalDescription(answer);

                window.wsClient?.send({
                    type: 'call_answer',
                    target: fromAddress,
                    call_id: callId,
                    sdp: answer
                });
                console.log('[answerCall] done, waiting for ICE/connection...');
            } catch(err) {
                console.error('[answerCall] error:', err);
                this.endCall();
                window.NotificationManager?.showToast('Cannot answer call: ' + err.message, 'error');
            } finally {
                setTimeout(() => { if (this.isEstablishing) this.isEstablishing = false; }, 5000);
            }
        }

        handleRemoteAnswer(answerSdp) {
            if (!this.pc || !this.pc.localDescription) {
                console.warn('[CallManager] handleRemoteAnswer: pc not ready, buffering answer');
                this.pendingAnswer = answerSdp;
                return;
            }
            this.pc.setRemoteDescription(new RTCSessionDescription(answerSdp))
                .then(() => {
                    console.log('[CallManager] Remote answer set successfully');
                    this.flushPendingCandidates();
                })
                .catch(err => console.error('[CallManager] setRemoteDescription(answer) failed:', err));
        }

        flushPendingAnswer() {
            if (!this.pendingAnswer || !this.pc) return;
            const ans = this.pendingAnswer;
            this.pendingAnswer = null;
            console.log('[CallManager] Flushing buffered answer');
            this.handleRemoteAnswer(ans);
        }

        handleRemoteIce(candidate) {
            if (!candidate) return;
            if (!this.pc || this.pc.signalingState === 'closed') {
                console.warn('[ICE] PeerConnection closed or closing, ignoring candidate');
                return;
            }
            const candidateInit = (typeof candidate === 'object' && 'candidate' in candidate)
                ? candidate
                : { candidate };
            console.log('[ICE] Received remote candidate:', candidateInit.candidate?.split(' ')[7], '| pc ready:', !!this.pc, '| remoteDesc:', !!this.pc?.remoteDescription);
            if (!this.pc || !this.pc.remoteDescription) {
                this.pendingCandidates.push(candidateInit);
                console.log('[ICE] Buffered (no remoteDescription yet), total:', this.pendingCandidates.length);
                return;
            }
            this.pc.addIceCandidate(new RTCIceCandidate(candidateInit))
                .then(() => console.log('[ICE] Remote candidate added OK'))
                .catch(err => console.error('[ICE] addIceCandidate failed:', err, candidateInit));
        }

        toggleMute() {
            if (!this.localStream) return;
            this.isMuted = !this.isMuted;
            this.localStream.getAudioTracks().forEach(track => track.enabled = !this.isMuted);
            const muteBtn = document.getElementById('callMuteBtn');
            if (muteBtn) {
                muteBtn.innerHTML = this.isMuted ? '🔇' : '🎤';
                muteBtn.classList.toggle('active', this.isMuted);
                muteBtn.title = this.t(this.isMuted ? 'call_unmute_microphone' : 'call_mute_microphone');
            }
        }

        async toggleSpeaker() {
            if (this.isIOS) {
                window.NotificationManager?.showToast('Speaker routing is automatic on iOS', 'info');
                return;
            }
            const audioElem = this.remoteAudio;
            if (!audioElem?.srcObject) {
                window.NotificationManager?.showToast('No active audio stream', 'error');
                return;
            }
            if (!audioElem.setSinkId) {
                window.NotificationManager?.showToast('Speaker switching not supported', 'error');
                return;
            }
            try {
                const devices = await navigator.mediaDevices.enumerateDevices();
                const outputs = devices.filter(d => d.kind === 'audiooutput');
                if (outputs.length < 2) {
                    window.NotificationManager?.showToast('Only one audio output available', 'info');
                    return;
                }
                await audioElem.setSinkId(this.isSpeakerEnabled ? outputs[0].deviceId : outputs[1].deviceId);
                this.isSpeakerEnabled = !this.isSpeakerEnabled;
                const speakerBtn = document.getElementById('callSpeakerBtn');
                if (speakerBtn) {
                    speakerBtn.innerHTML = this.isSpeakerEnabled ? '📢' : '🎧';
                    speakerBtn.classList.toggle('active', this.isSpeakerEnabled);
                    speakerBtn.title = this.t(this.isSpeakerEnabled ? 'call_earpiece' : 'call_speaker');
                }
            } catch(e) {
                console.warn('setSinkId error', e);
            }
        }

        reconnectCall() {
    if (!this.lastCallId || !this.lastFrom || !this.lastOffer) {
        window.NotificationManager?.showToast('No call to reconnect', 'error');
        return;
    }
    console.log('[CallManager] Reconnecting call', this.lastCallId);
    this.hideIncomingModal();
    this.answerCall(this.lastCallId, this.lastFrom, this.lastOffer, this.lastFromName);
}

        endCall() {
            this.stopIncomingSound();
            this.removeOutsideClickListener();
            this.stopCallTimer();
            if (this._connectTimeout) { clearTimeout(this._connectTimeout); this._connectTimeout = null; }
            if (this._disconnectTimer) { clearTimeout(this._disconnectTimer); this._disconnectTimer = null; }
            if (this.pc) {
                this.pc.onconnectionstatechange = null;
                this.pc.oniceconnectionstatechange = null;
                this.pc.onicegatheringstatechange = null;
                this.pc.onicecandidate = null;
                this.pc.ontrack = null;
                this.pc.close();
                this.pc = null;
            }
            this.closeMedia();
            this.pendingCandidates = [];
            this.pendingAnswer = null;
            if (this.currentPartner && this.currentCallId) {
                window.wsClient?.send({ type: 'call_hangup', target: this.currentPartner, call_id: this.currentCallId });
            }
            this.currentPartner = null;
            this.currentCallId = null;
            this.hideCallModal();
            this.hideMiniWidget();
            this.hideIncomingModal();
            this.updateCallStatus('ended');
            this.isCompactMode = false;
            this.isEstablishing = false;
            window.NotificationManager?.showToast(this.t('call_ended'), 'info');
        }

        rejectCall(callId, from) {
            window.wsClient?.send({ type: 'call_reject', target: from, call_id: callId });
            this.hideIncomingModal();
            window.NotificationManager?.showToast(this.t('call_rejected'), 'info');
        }

        showCallModal(state, statusText = '') {
            let modal = document.getElementById('callModal');
            if (!modal) return;
            if (!modal.classList.contains('hidden') && this.currentCallId && modal.dataset.callId === this.currentCallId) {
                console.log('[CallManager] Call modal already visible, skipping');
                return;
            }
            if (this.currentCallId) modal.dataset.callId = this.currentCallId;

            if (!document.getElementById('callDuration')) {
                const statusDiv = modal.querySelector('.call-status');
                if (statusDiv) {
                    const durationDiv = document.createElement('div');
                    durationDiv.id = 'callDuration';
                    durationDiv.className = 'call-duration';
                    durationDiv.style.marginTop = '8px';
                    durationDiv.style.fontSize = '14px';
                    durationDiv.style.fontWeight = '500';
                    statusDiv.after(durationDiv);
                }
            }

            modal.classList.remove('hidden');
            this.activeModal = 'call';
            this.isCompactMode = false;
            this.hideMiniWidget();
            this.addOutsideClickListener();

            const avatarEl = document.getElementById('callAvatar');
            const nameEl   = document.getElementById('callPartnerName');
            const statusEl = document.getElementById('callStatusText');
            if (nameEl)   nameEl.textContent   = this.currentPartnerName || this.currentPartner || 'Unknown';
            if (avatarEl) avatarEl.textContent  = (this.currentPartnerName?.[0] || '?').toUpperCase();
            if (statusEl) statusEl.textContent  = statusText || (state === 'outgoing' ? this.t('call_calling') : this.t('call_connected'));

            const muteBtn     = document.getElementById('callMuteBtn');
            const speakerBtn  = document.getElementById('callSpeakerBtn');
            const endBtn      = document.getElementById('callEndBtn');
            const collapseBtn = document.getElementById('callCollapseBtn');

            if (muteBtn) {
                muteBtn.innerHTML = '🎤';
                muteBtn.classList.remove('active');
                muteBtn.onclick = () => this.toggleMute();
                muteBtn.title = this.t('call_mute_microphone');
            }
            if (speakerBtn) {
                if (this.isIOS) {
                    speakerBtn.style.display = 'none';
                } else {
                    speakerBtn.style.display = '';
                    speakerBtn.innerHTML = '🎧';
                    speakerBtn.classList.remove('active');
                    speakerBtn.onclick = () => this.toggleSpeaker();
                    speakerBtn.title = this.t('call_speaker');
                }
            }
            if (endBtn) {
                endBtn.innerHTML = '📞';
                endBtn.onclick = () => this.endCall();
                endBtn.title = this.t('call_end');
            }
            if (collapseBtn) {
                collapseBtn.onclick = () => this.collapseToMini();
                collapseBtn.title = this.t('call_minimize');
            }

            this.isMuted = false;
            this.isSpeakerEnabled = false;
            this.updateLocalizedTexts();
        }

        collapseToMini() {
            if (this.isCompactMode) return;
            this.isCompactMode = true;
            this.hideCallModal();
            this.showMiniWidget();
            this.removeOutsideClickListener();
        }

        expandFromMini() {
            if (!this.isCompactMode) return;
            this.isCompactMode = false;
            this.hideMiniWidget();
            this.showCallModal('active', this.t('call_connected'));
        }

        showMiniWidget() {
            const widget = document.getElementById('callMiniWidget');
            if (!widget) return;
            widget.classList.remove('hidden');
            const nameSpan = document.getElementById('miniName');
            const statusSpan = document.getElementById('miniStatus');
            if (nameSpan)   nameSpan.textContent   = this.currentPartnerName || 'Call';
            if (statusSpan) statusSpan.textContent  = this.t('call_connected');
            this.updateLocalizedTexts();
        }

        hideMiniWidget() {
            document.getElementById('callMiniWidget')?.classList.add('hidden');
        }

        updateCallStatus(status) {
            const statusEl = document.getElementById('callStatusText');
            if (statusEl) {
                if (status === 'connected')        statusEl.textContent = this.t('call_connected');
                else if (status === 'calling')     statusEl.textContent = this.t('call_calling');
                else if (status === 'connecting')  statusEl.textContent = this.t('call_connecting');
                else                               statusEl.textContent = this.t('call_connecting');
            }
            const miniStatus = document.getElementById('miniStatus');
            if (miniStatus) {
                miniStatus.textContent = status === 'connected' ? this.t('call_connected') : this.t('call_connecting');
            }
        }

        hideCallModal() {
            const modal = document.getElementById('callModal');
            if (modal) modal.classList.add('hidden');
            this.activeModal = null;
            const rv = document.getElementById('remoteVideo');
            if (rv?.srcObject) rv.srcObject = null;
        }

        showIncomingCallModal(callId, from, offerSdp, fromName = '') {
            this.playIncomingSound();
            const modal = document.getElementById('incomingCallModal');
            if (!modal) return;
            if (this._incomingModalObserver) {
                this._incomingModalObserver.disconnect();
                this._incomingModalObserver = null;
            }
            modal.classList.remove('hidden');
            this.activeModal = 'incoming';
            modal.dataset.callId = callId;
            modal.dataset.from = from;
            modal.dataset.offerSdp = JSON.stringify(offerSdp);
            this.currentPartnerName = fromName || from.slice(0,16) + '…';

            const nameSpan = document.getElementById('incomingCallerName');
            if (nameSpan) nameSpan.textContent = this.currentPartnerName;

            const acceptBtn = document.getElementById('acceptCallBtn');
            const rejectBtn = document.getElementById('rejectCallBtn');

            if (acceptBtn) {
                acceptBtn.innerHTML = '✓';
                acceptBtn.title = this.t('call_accept');
                acceptBtn.onclick = async () => {
                    await this.unlockAudioContext();
                    let actualOffer = offerSdp;
                    if (!actualOffer || (typeof actualOffer === 'object' && !actualOffer?.sdp)) {
                        const raw = modal.dataset.offerSdp;
                        if (raw) {
                            try { actualOffer = JSON.parse(raw); } catch(e) { actualOffer = null; }
                        }
                    }
                    const actualCallId   = modal.dataset.callId   || callId;
                    const actualFrom     = modal.dataset.from      || from;
                    this.hideIncomingModal();
                    this.answerCall(actualCallId, actualFrom, actualOffer, fromName);
                };
            }
            if (rejectBtn) {
                rejectBtn.innerHTML = '✕';
                rejectBtn.title = this.t('call_reject');
                rejectBtn.onclick = () => {
                    this.rejectCall(callId, from);
                    this.hideIncomingModal();
                };
            }

            const fromLabel = modal.querySelector('.call-status');
            if (fromLabel) {
                fromLabel.innerHTML = `<span>${this.t('call_from')}</span> <strong id="incomingCallerName">${this.currentPartnerName}</strong>`;
            }
            const incomingTitle = modal.querySelector('.call-name');
            if (incomingTitle) incomingTitle.textContent = this.t('incoming_call');

            this.updateLocalizedTexts();

            setTimeout(() => {
                if (!modal.classList.contains('hidden') && !this._incomingModalObserver) {
                    this._incomingModalObserver = new MutationObserver((mutations) => {
                        for (const m of mutations) {
                            if (m.attributeName === 'class' && modal.classList.contains('hidden')) {
                                if (this.activeModal === 'incoming') {
                                    console.warn('[CallManager] Incoming modal was hidden externally, showing again');
                                    modal.classList.remove('hidden');
                                }
                            }
                        }
                    });
                    this._incomingModalObserver.observe(modal, { attributes: true });
                }
            }, 50);



        }

        showIncomingNotification(name, from) {
            if (!("Notification" in window)) return;
            const title = "📞 Incoming call";
            const options = {
                body: name || from,
                tag: "incoming-call",
                renotify: true,
                silent: false
            };
            if (Notification.permission === "granted") {
                const n = new Notification(title, options);
                n.onclick = () => {
                    window.focus();
                    this.showIncomingCallModal?.();
                };
            } else if (Notification.permission !== "denied") {
                Notification.requestPermission();
            }
        }

        hideIncomingModal() {
            if (this.activeModal === 'incoming') this.activeModal = null;
            if (this._incomingModalObserver) {
                this._incomingModalObserver.disconnect();
                this._incomingModalObserver = null;
            }
            const modal = document.getElementById('incomingCallModal');
            if (modal) modal.classList.add('hidden');
        }

        updateLocalizedTexts() {
            const miniStatus = document.getElementById('miniStatus');
            if (miniStatus) miniStatus.textContent = this.t('call_connected');
            const miniExpand = document.getElementById('miniExpandBtn');
            if (miniExpand) miniExpand.title = this.t('call_expand');
            const miniEnd = document.getElementById('miniEndBtn');
            if (miniEnd) miniEnd.title = this.t('call_end');

            const callModal = document.getElementById('callModal');
            if (callModal && !callModal.classList.contains('hidden')) {
                const statusEl = document.getElementById('callStatusText');
                if (statusEl) {
                    const cs = this.pc?.connectionState;
                    if (cs === 'connected') statusEl.textContent = this.t('call_connected');
                    else if (cs === 'connecting') statusEl.textContent = this.t('call_connecting');
                    else statusEl.textContent = this.t('call_calling');
                }
                const muteBtn = document.getElementById('callMuteBtn');
                if (muteBtn) muteBtn.title = this.t(this.isMuted ? 'call_unmute_microphone' : 'call_mute_microphone');
                const speakerBtn = document.getElementById('callSpeakerBtn');
                if (speakerBtn && !this.isIOS) speakerBtn.title = this.t(this.isSpeakerEnabled ? 'call_earpiece' : 'call_speaker');
                const endBtn = document.getElementById('callEndBtn');
                if (endBtn) endBtn.title = this.t('call_end');
                const collapseBtn = document.getElementById('callCollapseBtn');
                if (collapseBtn) collapseBtn.title = this.t('call_minimize');
            }

            const incomingModal = document.getElementById('incomingCallModal');
            if (incomingModal && !incomingModal.classList.contains('hidden')) {
                const fromLabel = incomingModal.querySelector('.call-status');
                if (fromLabel && this.currentPartnerName) {
                    fromLabel.innerHTML = `<span>${this.t('call_from')}</span> <strong>${this.currentPartnerName}</strong>`;
                }
                const incomingTitle = incomingModal.querySelector('.call-name');
                if (incomingTitle) incomingTitle.textContent = this.t('incoming_call');
                const acceptBtn = document.getElementById('acceptCallBtn');
                if (acceptBtn) acceptBtn.title = this.t('call_accept');
                const rejectBtn = document.getElementById('rejectCallBtn');
                if (rejectBtn) rejectBtn.title = this.t('call_reject');
            }

            document.querySelectorAll('#callModal [data-i18n-title], #incomingCallModal [data-i18n-title], #callMiniWidget [data-i18n-title]').forEach(el => {
                const key = el.getAttribute('data-i18n-title');
                if (key) el.title = this.t(key);
            });
        }
    }

    window.CallManager = new CallManager();
    window.CallManager.init();

    window.handleCallSignal = (data) => {
    const { type, call_id, from, sdp, candidate, from_name } = data;

    // Защита от старых сигналов (если call_id отличается от текущего)
    if (call_id && window.CallManager.currentCallId && call_id !== window.CallManager.currentCallId) {
        console.warn('[CallManager] stale signal ignored. current:', window.CallManager.currentCallId, 'received:', call_id);
        return;
    }

    if (type === 'incoming_call') {
        // Если уже есть активный звонок — автоматически отклоняем новый
        if (window.CallManager.currentCallId) {
            console.log('[CallManager] Busy, rejecting incoming call', call_id);
            window.wsClient?.send({ type: 'call_reject', target: from, call_id: call_id });
            window.NotificationManager?.showToast(
                window.CallManager.t('call_busy', 'User is busy'),
                'info'
            );
            return;
        }

        const callFrom = from || data.caller || data.sender || '';
        const callSdp  = sdp || data.offer || data.sdp_offer || null;
        const callName = from_name || data.caller_name || '';

        // Если это звонок из pending (после разблокировки) – очищаем sessionStorage
        const isPending = sessionStorage.getItem('pending_call_id') === call_id;
        if (isPending) {
            console.log('[handleCallSignal] Pending call – showing modal, waiting for user action');
            sessionStorage.removeItem('pending_call_id');
        }

        // Показываем модальное окно входящего звонка
        window.CallManager.showIncomingCallModal(call_id, callFrom, callSdp, callName);
        // Комментируем дублирующее нативное уведомление (push уже есть)

        return;
    }
    else if (type === 'call_answer') {
        if (!sdp) console.error('[handleCallSignal] call_answer has NO sdp!');
        window.CallManager.handleRemoteAnswer(sdp);
    }
    else if (type === 'call_ice') {
        if (!candidate) console.warn('[handleCallSignal] call_ice has NO candidate');
        window.CallManager.handleRemoteIce(candidate);
    }
    else if (type === 'call_hangup' || type === 'call_reject') {
        window.CallManager.endCall();
    }
};

})();