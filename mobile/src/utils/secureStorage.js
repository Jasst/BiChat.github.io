// src/utils/secureStorage.js
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import { pbkdf2 } from '@noble/hashes/pbkdf2';
import { sha256 } from '@noble/hashes/sha256';
import { gcm } from '@noble/ciphers/aes';
import { Buffer } from 'buffer';

const ITERATIONS = 100000;
const KEY_LENGTH = 32; // 256 бит
const SALT_LENGTH = 16;
const IV_LENGTH = 12;

// === Вспомогательные функции ===
function buf2hex(buffer) {
  return Array.from(new Uint8Array(buffer))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}

function hex2buf(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
  }
  return bytes;
}

// === Получение ключа из пароля (исправлено) ===
async function deriveKey(password, salt) {
  const enc = new TextEncoder();
  const passwordBytes = enc.encode(password); // теперь Uint8Array
  // salt уже Uint8Array
  const key = pbkdf2(sha256, passwordBytes, salt, {
    c: ITERATIONS,
    dkLen: KEY_LENGTH,
  });
  return key;
}

// === Шифрование мнемоники ===
export async function encryptMnemonic(mnemonic, password) {
  const salt = Crypto.getRandomBytes(SALT_LENGTH);
  const iv = Crypto.getRandomBytes(IV_LENGTH);
  const key = await deriveKey(password, salt);

  const aes = gcm(key);
  const plaintext = new TextEncoder().encode(mnemonic);
  const ciphertext = aes.encrypt(iv, plaintext);

  const result = {
    salt: buf2hex(salt),
    iv: buf2hex(iv),
    ciphertext: buf2hex(new Uint8Array(ciphertext)),
  };
  return JSON.stringify(result);
}

// === Дешифрование мнемоники ===
export async function decryptMnemonic(encryptedData, password) {
  try {
    const { salt, iv, ciphertext } = JSON.parse(encryptedData);
    const saltBytes = hex2buf(salt);
    const ivBytes = hex2buf(iv);
    const cipherBytes = hex2buf(ciphertext);

    const key = await deriveKey(password, saltBytes);
    const aes = gcm(key);
    const decrypted = aes.decrypt(ivBytes, cipherBytes);
    return new TextDecoder().decode(decrypted);
  } catch (e) {
    console.warn('Decryption failed:', e);
    return null;
  }
}

// Добавить в secureStorage.js:
export async function hasEncryptedMnemonic() {
  const data = await getEncryptedMnemonic();
  return !!data;
}

// === Сохранение зашифрованной мнемоники в SecureStore ===
export async function saveEncryptedMnemonic(encryptedData) {
  await SecureStore.setItemAsync('encrypted_mnemonic', encryptedData);
}

// === Получение зашифрованной мнемоники из SecureStore ===
export async function getEncryptedMnemonic() {
  return await SecureStore.getItemAsync('encrypted_mnemonic');
}

// === Удаление зашифрованной мнемоники ===
export async function clearEncryptedMnemonic() {
  await SecureStore.deleteItemAsync('encrypted_mnemonic');
}