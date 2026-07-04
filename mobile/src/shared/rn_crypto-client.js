/**
 * crypto-client.js — End-to-end шифрование на стороне клиента (React Native)
 * Версия: 5.0 — исправлены типы, обновлён API для @noble/ciphers >= 1.2.0
 */
import * as Crypto from 'expo-crypto';
import { Buffer } from 'buffer';
import { sha256 } from '@noble/hashes/sha256';
import { sha512 } from '@noble/hashes/sha512';
import { pbkdf2 } from '@noble/hashes/pbkdf2';
import { p256 } from '@noble/curves/p256';
import { gcm } from '@noble/ciphers/aes';
import { wordlist } from '../utils/wordlist.js';

// ============================================================
//  ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ПРИВЕДЕНИЯ К Uint8Array (БЕЗОПАСНАЯ)
// ============================================================
function toUint8Array(value) {
  if (value instanceof Uint8Array) return value;

  if (Buffer.isBuffer(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }

  if (value instanceof ArrayBuffer) {
    return new Uint8Array(value);
  }

  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }

  if (typeof value === 'string') {
    return new TextEncoder().encode(value);
  }

  throw new Error(`[toUint8Array] Unexpected type: ${typeof value}`);
}

// ============================================================
//  ПОЛУЧЕНИЕ СЛУЧАЙНЫХ БАЙТОВ (ВСЕГДА Uint8Array)
// ============================================================
const getRandomBytes = (size) => {
  const raw = Crypto.getRandomBytes(size);
  return toUint8Array(raw);
};

// ============================================================
//  ОСНОВНОЙ КЛАСС
// ============================================================
class DarkCrypto {
  // ------------------------------------------------------------------
  // 1. ГЕНЕРАЦИЯ МНЕМОНИКИ (BIP39)
  // ------------------------------------------------------------------
  static async generateMnemonic() {
    const entropy = getRandomBytes(32);
    const hash = sha256(entropy);
    const checksumBits = 8;
    const checksumByte = hash[0];
    const checksum = checksumByte >> (8 - checksumBits);

    const fullBits = [];
    for (let i = 0; i < entropy.length; i++) {
      for (let b = 7; b >= 0; b--) {
        fullBits.push((entropy[i] >> b) & 1);
      }
    }
    for (let b = checksumBits - 1; b >= 0; b--) {
      fullBits.push((checksum >> b) & 1);
    }

    const words = [];
    for (let i = 0; i < 24; i++) {
      let index = 0;
      for (let j = 0; j < 11; j++) {
        index = (index << 1) | fullBits[i * 11 + j];
      }
      words.push(wordlist[index]);
    }
    return words.join(' ');
  }

  // ------------------------------------------------------------------
  // 2. ДЕРИВАЦИЯ КЛЮЧЕЙ ИЗ МНЕМОНИКИ
  // ------------------------------------------------------------------
  static async deriveKeyPair(mnemonic) {
    const mnemonicBytes = new TextEncoder().encode(mnemonic);
    const saltBytes = new TextEncoder().encode('mnemonic');
    const seed = pbkdf2(sha512, mnemonicBytes, saltBytes, { c: 2048, dkLen: 64 });
    const rawPrivate = seed.slice(0, 32);
    const d = this._normalizePrivateKey(rawPrivate);
    const privateKey = d;
    const compressedPubKey = p256.getPublicKey(privateKey, true);
    const hash = sha256(compressedPubKey);
    const address = Array.from(hash).map(b => b.toString(16).padStart(2, '0')).join('');
    return {
      signPrivateKey: privateKey,
      ecdhPrivateKey: privateKey,
      compressedPubKey,
      address,
    };
  }

  // ------------------------------------------------------------------
  // 3. ДЕКОМПРЕССИЯ ПУБЛИЧНОГО КЛЮЧА
  // ------------------------------------------------------------------
  static decompressPublicKey(compressedKey) {
    const key = toUint8Array(compressedKey);
    try {
      return p256.ProjectivePoint.fromHex(key).toRawBytes(false);
    } catch (e) {
      throw new Error('Invalid compressed key: ' + e.message);
    }
  }

  // ------------------------------------------------------------------
  // 4. ECDH ОБЩИЙ СЕКРЕТ (С ПРИВЕДЕНИЕМ)
  // ------------------------------------------------------------------
  static async getSharedSecret(myPrivateKey, theirPubKeyBytes) {
    const priv = toUint8Array(myPrivateKey);
    const pub = toUint8Array(theirPubKeyBytes);

    if (pub.length !== 33 && pub.length !== 65) {
      throw new Error(
        `getSharedSecret: invalid public key length ${pub.length} (expected 33 or 65)`
      );
    }

    const shared = p256.getSharedSecret(priv, pub);
    const raw = toUint8Array(shared);

    if (raw.length === 33) {
      return raw.slice(1);
    } else if (raw.length === 65) {
      return raw.slice(1, 33);
    }
    return raw;
  }

  // ------------------------------------------------------------------
  // 5. AES-GCM ШИФРОВАНИЕ / ДЕШИФРОВАНИЕ (ИСПРАВЛЕННЫЕ)
  // ------------------------------------------------------------------
  // ------------------------------------------------------------------
// 5. AES-GCM ШИФРОВАНИЕ / ДЕШИФРОВАНИЕ (ДЛЯ @noble/ciphers >= 1.0)
// ------------------------------------------------------------------
static async encryptAES(sharedSecret, plaintext) {
  const key = toUint8Array(sharedSecret);
  const iv = getRandomBytes(12);
  const data = toUint8Array(plaintext);

  console.log('🔐 encryptAES key length:', key.length, 'iv length:', iv.length);

  const aes = gcm(key, iv);          // iv передаётся при создании
  const encrypted = aes.encrypt(data);

  return {
    ciphertext: toUint8Array(encrypted),
    iv,
  };
}

static async decryptAES(sharedSecret, ciphertext, iv) {
  const key = toUint8Array(sharedSecret);
  const nonce = toUint8Array(iv);
  const data = toUint8Array(ciphertext);

  const aes = gcm(key, nonce);       // nonce передаётся при создании
  const decrypted = aes.decrypt(data);

  return new TextDecoder().decode(toUint8Array(decrypted));
}

// ------------------------------------------------------------------
// 9. ФАЙЛОВЫЕ ОПЕРАЦИИ (аналогичное исправление)
// ------------------------------------------------------------------
static async encryptFile(fileData, key, iv) {
  const aes = gcm(toUint8Array(key), toUint8Array(iv));
  return aes.encrypt(toUint8Array(fileData));
}

static async decryptFile(encryptedData, key, iv) {
  const aes = gcm(toUint8Array(key), toUint8Array(iv));
  return aes.decrypt(toUint8Array(encryptedData));
}

  // ------------------------------------------------------------------
  // 6. ШИФРОВАНИЕ / ДЕШИФРОВАНИЕ СООБЩЕНИЙ
  // ------------------------------------------------------------------
  static async encryptMessage(myPrivateKey, myPubKey, recipientPubKey, plaintext) {
    const shared = await this.getSharedSecret(myPrivateKey, recipientPubKey);
    const { ciphertext, iv } = await this.encryptAES(shared, plaintext);
    return {
      ciphertext: this._arrayBufferToBase64(ciphertext),
      iv: this._toBase64(iv),
      myPubKey: this._toBase64(myPubKey),
    };
  }

  static async decryptMessage(myPrivateKey, senderPubKey, ivBase64, ciphertextBase64) {
    const senderPub = toUint8Array(
      typeof senderPubKey === 'string' ? this._fromBase64(senderPubKey) : senderPubKey
    );
    const iv = this._fromBase64(ivBase64);
    const ciphertext = this._fromBase64(ciphertextBase64);
    const shared = await this.getSharedSecret(myPrivateKey, senderPub);
    return await this.decryptAES(shared, ciphertext, iv);
  }

  // ------------------------------------------------------------------
  // 7. ПОДПИСЬ / ВЕРИФИКАЦИЯ
  // ------------------------------------------------------------------
  static async signData(privateKey, dataString) {
    const priv = toUint8Array(privateKey);
    const msgHash = sha256(new TextEncoder().encode(dataString));
    const sig = p256.sign(msgHash, priv);
    return sig.toCompactRawBytes();
  }

  static async verifySignature(publicKeyBytes, signature, dataString) {
    const pub = toUint8Array(publicKeyBytes);
    const sig = p256.Signature.fromCompact(signature);
    const msgHash = sha256(new TextEncoder().encode(dataString));
    return p256.verify(sig, msgHash, pub);
  }

  // ------------------------------------------------------------------
  // 8. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ (БЕЗОПАСНОЕ ПРИВЕДЕНИЕ)
  // ------------------------------------------------------------------
  static _normalizePrivateKey(rawBytes) {
    const bytes = toUint8Array(rawBytes);
    const n = BigInt('0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551');
    let scalar = 0n;
    for (let i = 0; i < bytes.length; i++) {
      scalar = (scalar << 8n) | BigInt(bytes[i]);
    }
    scalar = (scalar % (n - 1n)) + 1n;
    const hex = scalar.toString(16).padStart(64, '0');
    const result = new Uint8Array(32);
    for (let i = 0; i < 32; i++) {
      result[i] = parseInt(hex.substring(i * 2, i * 2 + 2), 16);
    }
    return result;
  }

  static _to32Bytes(value) {
    const hex = value.toString(16).padStart(64, '0');
    const bytes = new Uint8Array(32);
    for (let i = 0; i < 32; i++) {
      bytes[i] = parseInt(hex.substring(i * 2, i * 2 + 2), 16);
    }
    return bytes;
  }

  static _toBase64(arr) {
    return Buffer.from(toUint8Array(arr)).toString('base64');
  }

  static _fromBase64(str) {
    if (typeof str !== 'string') {
      throw new Error(`_fromBase64: expected string, got ${typeof str}`);
    }
    return new Uint8Array(Buffer.from(str, 'base64'));
  }

  static _arrayBufferToBase64(buffer) {
    return Buffer.from(toUint8Array(buffer)).toString('base64');
  }

  static _base64ToArrayBuffer(base64) {
    const buffer = Buffer.from(base64, 'base64');
    return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  }

  static _bytesToBase64Url(bytes) {
    return Buffer.from(toUint8Array(bytes))
      .toString('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
  }

  static _base64UrlToBytes(base64url) {
    const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
    return new Uint8Array(Buffer.from(base64, 'base64'));
  }

  static _concat(a, b) {
    const A = toUint8Array(a);
    const B = toUint8Array(b);
    const c = new Uint8Array(A.length + B.length);
    c.set(A, 0);
    c.set(B, A.length);
    return c;
  }

  // ------------------------------------------------------------------
  // 9. ФАЙЛОВЫЕ ОПЕРАЦИИ (С ПРИВЕДЕНИЕМ)
  // ------------------------------------------------------------------

  static generateFileKeyAndIv() {
    return {
      key: getRandomBytes(32),
      iv: getRandomBytes(12),
    };
  }

  static arrayBufferToBase64(buffer) {
    return Buffer.from(toUint8Array(buffer)).toString('base64');
  }

  static base64ToArrayBuffer(base64) {
    const buffer = Buffer.from(base64, 'base64');
    return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  }
}

export default DarkCrypto;