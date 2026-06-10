/**
 * call-manager.js — WebRTC звонки (голос/видео)
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
            this.isInitiator = false;
            this.isAudioOnly = true;   // можно сделать выбор пользователя
            this.iceServers = [];
        }

        async init() {
            // Получить ICE-сервера с бэкенда
            try {
                const res = await fetch('/calls/turn-credentials');
                const data = await res.json();
                this.iceServers = data.iceServers;
                console.log('ICE servers loaded', this.iceServers);
            } catch(e) {
                console.warn('Failed to load TURN config, fallback to STUN only', e);
                this.iceServers = [{ urls: 'stun:stun.l.google.com:19302' }];
            }
        }

        async getUserMedia() {
            if (this.localStream) return this.localStream;
            try {
                const constraints = { audio: true, video: !this.isAudioOnly };
                this.localStream = await navigator.mediaDevices.getUserMedia(constraints);
                return this.localStream;
            } catch(e) {
                console.error('Media access denied', e);
                throw new Error('Cannot access microphone/camera');
            }
        }

        closeMedia() {
            if (this.localStream) {
                this.localStream.getTracks().forEach(track => track.stop());
                this.localStream = null;
            }
        }

        async makeCall(partnerAddress, isVideo = false) {
            this.isAudioOnly = !isVideo;
            this.currentPartner = partnerAddress;
            this.isInitiator = true;
            this.currentCallId = `call_${Date.now()}_${Math.random().toString(36)}`;

            try {
                const stream = await this.getUserMedia();
                this.createPeerConnection();
                stream.getTracks().forEach(track => this.pc.addTrack(track, stream));

                const offer = await this.pc.createOffer();
                await this.pc.setLocalDescription(offer);

                // Отправить offer через WebSocket
                window.wsClient?.send({
                    type: 'call_offer',
                    target: partnerAddress,
                    call_id: this.currentCallId,
                    sdp: offer
                });

                this.showCallUI('calling');
            } catch(err) {
                console.error(err);
                this.endCall();
                window.NotificationManager.showToast('Cannot start call: ' + err.message, 'error');
            }
        }

        createPeerConnection() {
            if (this.pc) this.pc.close();
            this.pc = new RTCPeerConnection({ iceServers: this.iceServers });

            this.pc.onicecandidate = (event) => {
                if (event.candidate && this.currentPartner) {
                    window.wsClient?.send({
                        type: 'call_ice',
                        target: this.currentPartner,
                        call_id: this.currentCallId,
                        candidate: event.candidate
                    });
                }
            };

            this.pc.ontrack = (event) => {
                // Отображать удалённый аудио/видео
                this.attachRemoteStream(event.streams[0]);
            };

            this.pc.onconnectionstatechange = () => {
                if (this.pc.connectionState === 'failed' || this.pc.connectionState === 'closed') {
                    this.endCall();
                }
            };
        }

        attachRemoteStream(stream) {
            // Показать видео (если есть) или только аудио
            const remoteVideo = document.getElementById('remoteVideo');
            if (remoteVideo) {
                remoteVideo.srcObject = stream;
                remoteVideo.play().catch(e=>console.warn);
            }
            // Показать модалку разговора, скрыть кнопки вызова
            document.getElementById('callModal')?.classList.remove('hidden');
            document.getElementById('callStatus').innerText = 'In call...';
        }

        async answerCall(callId, fromAddress, offerSdp) {
            this.currentCallId = callId;
            this.currentPartner = fromAddress;
            this.isInitiator = false;
            try {
                const stream = await this.getUserMedia();
                this.createPeerConnection();
                stream.getTracks().forEach(track => this.pc.addTrack(track, stream));
                await this.pc.setRemoteDescription(new RTCSessionDescription(offerSdp));
                const answer = await this.pc.createAnswer();
                await this.pc.setLocalDescription(answer);

                window.wsClient?.send({
                    type: 'call_answer',
                    target: fromAddress,
                    call_id: callId,
                    sdp: answer
                });
                this.showCallUI('in_call');
            } catch(err) {
                console.error(err);
                this.endCall();
            }
        }

        handleRemoteAnswer(answerSdp) {
            this.pc?.setRemoteDescription(new RTCSessionDescription(answerSdp)).catch(console.error);
        }

        handleRemoteIce(candidate) {
            if (this.pc) {
                this.pc.addIceCandidate(new RTCIceCandidate(candidate)).catch(console.error);
            }
        }

        endCall() {
            if (this.pc) {
                this.pc.close();
                this.pc = null;
            }
            this.closeMedia();
            if (this.currentPartner && this.currentCallId) {
                window.wsClient?.send({
                    type: 'call_hangup',
                    target: this.currentPartner,
                    call_id: this.currentCallId
                });
            }
            this.currentPartner = null;
            this.currentCallId = null;
            this.hideCallUI();
        }

        rejectCall(callId, from) {
            window.wsClient?.send({
                type: 'call_reject',
                target: from,
                call_id: callId
            });
            this.hideCallUI();
        }

        showCallUI(state) {
            const modal = document.getElementById('callModal');
            if (!modal) return;
            modal.classList.remove('hidden');
            const statusEl = document.getElementById('callStatus');
            if (state === 'calling') statusEl.innerText = 'Calling...';
            else if (state === 'in_call') statusEl.innerText = 'Connected';
            else if (state === 'incoming') statusEl.innerText = 'Incoming call...';
        }

        hideCallUI() {
            const modal = document.getElementById('callModal');
            if (modal) modal.classList.add('hidden');
            const remoteVideo = document.getElementById('remoteVideo');
            if (remoteVideo && remoteVideo.srcObject) {
                remoteVideo.srcObject.getTracks().forEach(t => t.stop());
                remoteVideo.srcObject = null;
            }
        }

        // Показать модалку входящего звонка
        showIncomingCallModal(callId, from, offerSdp) {
            const modal = document.getElementById('incomingCallModal');
            if (!modal) return;
            modal.classList.remove('hidden');
            modal.dataset.callId = callId;
            modal.dataset.from = from;
            modal.dataset.offerSdp = JSON.stringify(offerSdp);
            document.getElementById('incomingCallerName').innerText = from.slice(0,10)+'…';
        }
    }

    window.CallManager = new CallManager();
    window.CallManager.init();

    // Обработчики событий (будут вызваны из core.js)
    window.handleCallSignal = (data) => {
        const { type, call_id, from, sdp, candidate } = data;
        if (type === 'incoming_call') {
            window.CallManager.showIncomingCallModal(call_id, from, sdp);
        } else if (type === 'call_answer') {
            window.CallManager.handleRemoteAnswer(sdp);
        } else if (type === 'call_ice') {
            window.CallManager.handleRemoteIce(candidate);
        } else if (type === 'call_hangup') {
            window.CallManager.endCall();
            window.NotificationManager.showToast('Call ended', 'info');
        } else if (type === 'call_reject') {
            window.CallManager.endCall();
            window.NotificationManager.showToast('Call rejected', 'info');
        }
    };
    document.addEventListener('click', (e) => {
    if (e.target.id === 'acceptCallBtn') {
        const modal = document.getElementById('incomingCallModal');
        const callId = modal.dataset.callId;
        const from = modal.dataset.from;
        const offerSdp = JSON.parse(modal.dataset.offerSdp);
        window.CallManager.answerCall(callId, from, offerSdp);
        modal.classList.add('hidden');
    } else if (e.target.id === 'rejectCallBtn') {
        const modal = document.getElementById('incomingCallModal');
        const callId = modal.dataset.callId;
        const from = modal.dataset.from;
        window.CallManager.rejectCall(callId, from);
        modal.classList.add('hidden');
    }
});

})();