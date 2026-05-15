// client-crypto.js — End-to-end шифрование на стороне браузера
import { generateMnemonic, mnemonicToSeedSync } from '@scure/bip39';
import { HDKey } from '@scure/bip32';
import { secp256k1 } from '@noble/curves/secp256k1';
import { sha256 } from '@noble/hashes/sha256';
import { hkdf } from '@noble/hashes/hkdf';
import { gcm } from '@noble/ciphers/aes';

const PBKDF2_ITERATIONS = 600_000;
const DOMAIN_SEPARATOR = "BiChat:crypto:v3.3";

// Деривация ключа из мнемоники (аналог crypto_manager.py)
export function deriveKeyPair(mnemonic) {
  const seed = mnemonicToSeedSync(mnemonic, '');
  // BIP32 путь (или прямая деривация через хэши)
  const hdkey = HDKey.fromMasterSeed(seed).derive("m/44'/0'/0'/0/0");
  if (!hdkey.privateKey) throw new Error('No private key');
  // secp256k1 (в проекте используется P-256, но можно адаптировать)
  const pubKey = secp256k1.getPublicKey(hdkey.privateKey, true); // compressed
  return {
    privateKey: hdkey.privateKey,
    publicKey: pubKey,
    address: sha256(pubKey).toHex()
  };
}

// ECDH общий секрет (на сервер не уходит)
export function computeSharedSecret(myPrivKey, peerPubKeyBytes) {
  return sha256(secp256k1.getSharedSecret(myPrivKey, peerPubKeyBytes));
}

// Гибридное шифрование
export async function encryptHybrid(myPrivKey, peerPubKey, plaintext) {
  const secret = computeSharedSecret(myPrivKey, peerPubKey);
  const sessionKey = crypto.getRandomValues(new Uint8Array(32));
  const encSessionKey = await aesGcmEncrypt(sessionKey, secret); // зашифровываем сессионный ключ
  const ciphertext = plaintext ? await aesGcmEncrypt(new TextEncoder().encode(plaintext), sessionKey) : '';
  return {
    enc_session_key: encSessionKey,
    content: ciphertext,
    version: 'hybrid-v2'
  };
}
// ... и аналогично decryptHybrid