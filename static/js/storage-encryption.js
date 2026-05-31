// static/js/storage-encryption.js
(function() {
    if (window.StorageEncryption) return;
    window.StorageEncryption = {};

    function buf2hex(buffer) {
        return Array.from(new Uint8Array(buffer)).map(b => b.toString(16).padStart(2, '0')).join('');
    }

    function hex2buf(hex) {
        const bytes = new Uint8Array(hex.length / 2);
        for (let i = 0; i < hex.length; i += 2) {
            bytes[i/2] = parseInt(hex.substr(i, 2), 16);
        }
        return bytes.buffer;
    }

    async function pbkdf2(password, salt, iterations = 100000, length = 32) {
        const enc = new TextEncoder();
        const keyMaterial = await crypto.subtle.importKey(
            'raw', enc.encode(password), 'PBKDF2', false, ['deriveBits']
        );
        return await crypto.subtle.deriveBits(
            { name: 'PBKDF2', salt, iterations, hash: 'SHA-256' },
            keyMaterial, length * 8
        );
    }

    window.StorageEncryption.encryptMnemonic = async function(mnemonic, password) {
        const salt = crypto.getRandomValues(new Uint8Array(16));
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const keyBytes = await pbkdf2(password, salt, 100000, 32);
        const key = await crypto.subtle.importKey('raw', keyBytes, 'AES-GCM', false, ['encrypt']);
        const enc = new TextEncoder();
        const encrypted = await crypto.subtle.encrypt(
            { name: 'AES-GCM', iv },
            key,
            enc.encode(mnemonic)
        );
        return JSON.stringify({
            salt: buf2hex(salt),
            iv: buf2hex(iv),
            ciphertext: buf2hex(new Uint8Array(encrypted))
        });
    };

    window.StorageEncryption.decryptMnemonic = async function(encryptedData, password) {
        try {
            const { salt, iv, ciphertext } = JSON.parse(encryptedData);
            const saltBytes = new Uint8Array(hex2buf(salt));
            const ivBytes = new Uint8Array(hex2buf(iv));
            const cipherBytes = new Uint8Array(hex2buf(ciphertext));
            const keyBytes = await pbkdf2(password, saltBytes, 100000, 32);
            const key = await crypto.subtle.importKey('raw', keyBytes, 'AES-GCM', false, ['decrypt']);
            const decrypted = await crypto.subtle.decrypt(
                { name: 'AES-GCM', iv: ivBytes },
                key,
                cipherBytes
            );
            return new TextDecoder().decode(decrypted);
        } catch(e) {
            console.warn('Decryption failed', e);
            return null;
        }
    };
})();