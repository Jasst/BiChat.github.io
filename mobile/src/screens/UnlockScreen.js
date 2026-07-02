// src/screens/UnlockScreen.js
import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { BlurView } from 'expo-blur';
import { colors, glassStyle } from '../theme';
import { OvalButton } from '../components/OvalButton';
import useUserStore from '../store/userStore';
import { decryptMnemonic, clearEncryptedMnemonic } from '../utils/secureStorage';
import DarkCrypto from '../shared/crypto-client';
import { storage } from '../utils/storage';
import { API_BASE_URL } from '../config/constants';
import { initWebSocket, startHeartbeat, startStatusPolling, startUserStatusPolling } from '../shared/core';

export default function UnlockScreen({ navigation }) {
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const { encryptedMnemonic, setAddress, setAuthenticated, setNeedsUnlock } = useUserStore();

  const handleUnlock = async () => {
    if (!password.trim()) {
      Alert.alert('Error', 'Please enter your password');
      return;
    }
    setLoading(true);
    try {
      const mnemonic = await decryptMnemonic(encryptedMnemonic, password);
      if (!mnemonic) {
        await clearEncryptedMnemonic();
        Alert.alert('Error', 'Failed to decrypt wallet. Please login again.');
        navigation.replace('Login');
        return;
      }

      const keys = await DarkCrypto.deriveKeyPair(mnemonic);
      const { address } = keys;

      await storage.setItem('mnemonic', mnemonic);
      await storage.setItem('userAddress', address);
      setAddress(address);
      setAuthenticated(true);
      setNeedsUnlock(false, null);

      // ✅ ПРОВЕРЯЕМ И ПОЛУЧАЕМ NONCE, ЕСЛИ ЕГО НЕТ
      let nonce = await storage.getItem('nonce');
      if (!nonce) {
        try {
          const nonceRes = await fetch(`${API_BASE_URL}/nonce`);
          if (nonceRes.ok) {
            const nonceData = await nonceRes.json();
            nonce = nonceData.nonce;
            await storage.setItem('nonce', nonce);
          } else {
            throw new Error('Could not get nonce');
          }
        } catch (e) {
          console.warn('Nonce fetch failed:', e);
        }
      }

      await initWebSocket();
      startHeartbeat();
      startStatusPolling();
      startUserStatusPolling();

      navigation.replace('Main');
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
        <Text style={styles.title}>🔐 Unlock Wallet</Text>
        <Text style={styles.subtitle}>
          Your encrypted wallet was found. Enter password to unlock.
        </Text>
        <TextInput
          style={styles.input}
          placeholder="Password"
          placeholderTextColor={colors.textMuted}
          secureTextEntry
          value={password}
          onChangeText={setPassword}
          autoFocus
        />
        <OvalButton
          title="Unlock"
          primary
          loading={loading}
          onPress={handleUnlock}
          style={styles.fullWidth}
        />
        <OvalButton
          title="Log out (clear encrypted data)"
          onPress={async () => {
            await clearEncryptedMnemonic();
            setNeedsUnlock(false, null);
            navigation.replace('Login');
          }}
          style={[styles.fullWidth, styles.logoutBtn]}
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
    marginBottom: 8,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 16,
    color: colors.textMuted,
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
  fullWidth: {
    width: '100%',
    marginTop: 8,
  },
  logoutBtn: {
    marginTop: 12,
    borderColor: colors.danger,
    borderWidth: 1,
    backgroundColor: 'transparent',
  },
});