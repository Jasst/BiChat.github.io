// static/js/crypto-client.js (исправленная версия)
// Подключается через script type="module"

// CDN импорты
import { generateMnemonic, mnemonicToSeedSync } from 'https://esm.sh/@scure/bip39@1.3.0';
import { HDKey } from 'https://esm.sh/@scure/bip32@1.4.0';
import { secp256k1 } from 'https://esm.sh/@noble/curves@1.4.0/secp256k1';
import { sha256 } from 'https://esm.sh/@noble/hashes@1.4.0/sha256';

const PBKDF2_ITERATIONS = 600_000;
const DOMAIN_SEPARATOR = "BiChat:crypto:v3.3";

// Деривация ключа из мнемоники
export function deriveKeyPair(mnemonic) {
  const seed = mnemonicToSeedSync(mnemonic, '');
  const hdkey = HDKey.fromMasterSeed(seed).derive("m/44'/0'/0'/0/0");
  if (!hdkey.privateKey) throw new Error('No private key');
  const pubKey = secp256k1.getPublicKey(hdkey.privateKey, true);
  return {
    privateKey: hdkey.privateKey,
    publicKey: pubKey,
    address: sha256(pubKey).toHex()
  };
}

// ECDH общий секрет
export function computeSharedSecret(myPrivKey, peerPubKeyBytes) {
  return sha256(secp256k1.getSharedSecret(myPrivKey, peerPubKeyBytes));
}

// Простое AES-GCM шифрование (без зависимостей от @noble/ciphers)
async function aesGcmEncrypt(plaintext, key) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const cryptoKey = await crypto.subtle.importKey('raw', key, { name: 'AES-GCM' }, false, ['encrypt']);
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, cryptoKey, plaintext);
  const result = new Uint8Array(iv.length + ciphertext.byteLength);
  result.set(iv);
  result.set(new Uint8Array(ciphertext), iv.length);
  return result;
}

async function aesGcmDecrypt(ciphertextWithIv, key) {
  const iv = ciphertextWithIv.slice(0, 12);
  const ciphertext = ciphertextWithIv.slice(12);
  const cryptoKey = await crypto.subtle.importKey('raw', key, { name: 'AES-GCM' }, false, ['decrypt']);
  const plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, cryptoKey, ciphertext);
  return new Uint8Array(plaintext);
}

// Гибридное шифрование
export async function encryptHybrid(myPrivKey, peerPubKey, plaintext) {
  const secret = computeSharedSecret(myPrivKey, peerPubKey);
  const sessionKey = crypto.getRandomValues(new Uint8Array(32));
  const encSessionKey = await aesGcmEncrypt(sessionKey, secret);
  const ciphertext = plaintext ? await aesGcmEncrypt(new TextEncoder().encode(plaintext), sessionKey) : new Uint8Array(0);
  return {
    enc_session_key: Array.from(encSessionKey),
    content: Array.from(ciphertext),
    version: 'hybrid-v2'
  };
}

// Гибридное дешифрование
export async function decryptHybrid(myPrivKey, peerPubKey, encData) {
  const secret = computeSharedSecret(myPrivKey, peerPubKey);
  const sessionKey = await aesGcmDecrypt(new Uint8Array(encData.enc_session_key), secret);
  const plaintext = await aesGcmDecrypt(new Uint8Array(encData.content), sessionKey);
  return new TextDecoder().decode(plaintext);
}

// Экспорт в window для доступа из обычных скриптов
if (typeof window !== 'undefined') {
  window.DarkCrypto = {
    deriveKeyPair,
    computeSharedSecret,
    encryptHybrid,
    decryptHybrid,
    _fromBase64: (str) => Uint8Array.from(atob(str), c => c.charCodeAt(0)),
    _toBase64: (bytes) => btoa(String.fromCharCode(...bytes)),
    _arrayBufferToBase64: (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))),
    _base64ToArrayBuffer: (base64) => Uint8Array.from(atob(base64), c => c.charCodeAt(0)).buffer,
    getSharedSecret: computeSharedSecret,
    encryptAES: async (key, text) => {
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const cryptoKey = await crypto.subtle.importKey('raw', key, { name: 'AES-GCM' }, false, ['encrypt']);
      const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, cryptoKey, new TextEncoder().encode(text));
      return { ciphertext, iv };
    },
    decryptAES: async (key, ciphertext, iv) => {
      const cryptoKey = await crypto.subtle.importKey('raw', key, { name: 'AES-GCM' }, false, ['decrypt']);
      const plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, cryptoKey, ciphertext);
      return new TextDecoder().decode(plaintext);
    },
    encryptMessage: async (myPriv, myPub, peerPub, text) => {
      const secret = computeSharedSecret(myPriv, peerPub);
      const sessionKey = crypto.getRandomValues(new Uint8Array(32));
      const encSessionKey = await aesGcmEncrypt(sessionKey, secret);
      const ciphertext = await aesGcmEncrypt(new TextEncoder().encode(text), sessionKey);
      return {
        ciphertext: btoa(String.fromCharCode(...ciphertext)),
        iv: btoa(String.fromCharCode(...new Uint8Array(12))),
        myPubKey: btoa(String.fromCharCode(...myPub))
      };
    }
  };
}