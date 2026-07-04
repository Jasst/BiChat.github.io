// src/screens/LoginScreen.js
import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  Alert,
  ActivityIndicator,
  Switch,
} from 'react-native';
import { BlurView } from 'expo-blur';
import { colors, glassStyle } from '../theme';
import { OvalButton } from '../components/OvalButton';
import DarkCrypto from '../shared/rn_crypto-client';
import useUserStore from '../store/userStore';
import { storage } from '../utils/storage';
import { API_BASE_URL } from '../config/constants';
import { initWebSocket, startHeartbeat, startStatusPolling, startUserStatusPolling } from '../shared/rn_core';

export default function LoginScreen({ navigation }) {
  const [mnemonic, setMnemonic] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const { setAddress, setAuthenticated } = useUserStore();

  const handleLogin = async () => {
    if (!mnemonic.trim()) {
      Alert.alert('Error', 'Enter your mnemonic phrase');
      return;
    }
    if (remember && !password.trim()) {
      Alert.alert('Error', 'Please enter an encryption password to remember your wallet');
      return;
    }

    setLoading(true);
    try {
      const trimmedMnemonic = mnemonic.trim();
      console.log('[Login] step 1: deriveKeyPair start');
      const keys = await DarkCrypto.deriveKeyPair(trimmedMnemonic);
      console.log('[Login] step 1: deriveKeyPair OK', {
        addressLen: keys.address?.length,
        signPrivateKeyType: keys.signPrivateKey?.constructor?.name,
        signPrivateKeyLen: keys.signPrivateKey?.length,
        compressedPubKeyType: keys.compressedPubKey?.constructor?.name,
        compressedPubKeyLen: keys.compressedPubKey?.length,
      });
      const { address, compressedPubKey, signPrivateKey } = keys;

      // Получаем nonce с сервера
      console.log('[Login] step 2: fetching nonce');
      const nonceRes = await fetch(`${API_BASE_URL}/nonce`);
      if (!nonceRes.ok) throw new Error('Could not get nonce from server');
      const nonceData = await nonceRes.json();
      const nonce = nonceData.nonce;
      console.log('[Login] step 2: nonce OK', { nonceType: typeof nonce, nonceValue: nonce });

      console.log('[Login] step 3: signData start');
      const signatureArray = await DarkCrypto.signData(signPrivateKey, nonce);
      console.log('[Login] step 3: signData OK', {
        sigType: signatureArray?.constructor?.name,
        sigLen: signatureArray?.length,
      });
      const signatureHex = Array.from(new Uint8Array(signatureArray))
        .map(b => b.toString(16).padStart(2, '0')).join('');
      console.log('[Login] step 4: signatureHex OK', signatureHex?.slice(0, 16) + '...');
      const pubkeyB64 = DarkCrypto._toBase64(compressedPubKey);
      console.log('[Login] step 5: pubkeyB64 OK');

      const loginRes = await fetch(`${API_BASE_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address, public_key: pubkeyB64, signature: signatureHex, nonce })
      });
      const loginData = await loginRes.json();

      if (loginRes.ok) {
        // ✅ Сохраняем nonce из ответа /login (сервер должен его вернуть)
        const serverNonce = loginData.nonce;
        if (serverNonce) {
          await storage.setItem('nonce', serverNonce);
        } else {
          // fallback: используем тот, что получили от /nonce
          await storage.setItem('nonce', nonce);
        }

        await storage.setItem('mnemonic', trimmedMnemonic);
        await storage.setItem('userAddress', address);
        setAddress(address);
        setAuthenticated(true);

        if (remember && password) {
          const { encryptMnemonic, saveEncryptedMnemonic } = await import('../utils/secureStorage');
          const encrypted = await encryptMnemonic(trimmedMnemonic, password);
          await saveEncryptedMnemonic(encrypted);
        }

        await initWebSocket();
        startHeartbeat();
        startStatusPolling();
        startUserStatusPolling();

        navigation.replace('Main');
      } else {
        Alert.alert('Login failed', loginData.error || 'Invalid credentials');
      }
    } catch (error) {
      console.error(error);
      Alert.alert('Error', error.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <BlurView intensity={20} tint="dark" style={[styles.card, glassStyle]}>
        <Text style={styles.title}>Login</Text>
        <TextInput
          style={[styles.input, styles.mnemonicInput]}
          placeholder="Enter your 24-word mnemonic"
          placeholderTextColor={colors.textMuted}
          multiline
          numberOfLines={4}
          value={mnemonic}
          onChangeText={setMnemonic}
          autoCapitalize="none"
        />
        <TextInput
          style={styles.input}
          placeholder="Encryption password (required if remembering)"
          placeholderTextColor={colors.textMuted}
          secureTextEntry
          value={password}
          onChangeText={setPassword}
        />
        <View style={styles.switchRow}>
          <Switch
            value={remember}
            onValueChange={setRemember}
            trackColor={{ false: '#2a2a2a', true: colors.accent }}
            thumbColor={remember ? '#fff' : '#f4f3f4'}
          />
          <Text style={styles.switchLabel}>Remember me (encrypt wallet locally)</Text>
        </View>
        <OvalButton
          title="Login"
          primary
          loading={loading}
          onPress={handleLogin}
          style={styles.fullWidth}
        />
      </BlurView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  card: {
    width: '100%',
    maxWidth: 480,
    padding: 24,
    ...glassStyle,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: colors.textMain,
    marginBottom: 30,
    textAlign: 'center',
  },
  input: {
    backgroundColor: 'rgba(0,0,0,0.3)',
    borderWidth: 1,
    borderColor: colors.glassBorder,
    borderRadius: 50,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: colors.textMain,
    fontSize: 16,
    marginBottom: 16,
  },
  mnemonicInput: {
    minHeight: 80,
    textAlignVertical: 'top',
    borderRadius: 16,
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 20,
    gap: 12,
  },
  switchLabel: {
    color: colors.textMuted,
    fontSize: 14,
    flexShrink: 1,
  },
  fullWidth: {
    width: '100%',
  },
});