// src/screens/CreateWalletScreen.js
import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  Alert,
  ActivityIndicator,
  Switch,
  ScrollView,
} from 'react-native';
import { BlurView } from 'expo-blur';
import { colors, glassStyle } from '../theme';
import { OvalButton } from '../components/OvalButton';
import DarkCrypto from '../shared/crypto-client';
import useUserStore from '../store/userStore';
import { storage } from '../utils/storage';
import { API_BASE_URL } from '../config/constants';
import { initWebSocket, startHeartbeat, startStatusPolling, startUserStatusPolling } from '../shared/core';

export default function CreateWalletScreen({ navigation }) {
  const [mnemonic, setMnemonic] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saveLocally, setSaveLocally] = useState(true);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const { setAddress, setAuthenticated } = useUserStore();

  const generateWallet = async () => {
    if (saveLocally) {
      if (!password.trim() || password.length < 4) {
        Alert.alert('Error', 'Password must be at least 4 characters');
        return;
      }
      if (password !== confirmPassword) {
        Alert.alert('Error', 'Passwords do not match');
        return;
      }
    }

    setLoading(true);
    try {
      const newMnemonic = await DarkCrypto.generateMnemonic();
      const keys = await DarkCrypto.deriveKeyPair(newMnemonic);
      const { address, compressedPubKey } = keys;

      const pubkeyB64 = DarkCrypto._toBase64(compressedPubKey);
      const registerRes = await fetch(`${API_BASE_URL}/create_wallet`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address, public_key: pubkeyB64 })
      });
      const registerData = await registerRes.json();

      if (!registerRes.ok) {
        throw new Error(registerData.error || 'Registration failed');
      }

      // Сохраняем мнемонику и адрес
      await storage.setItem('mnemonic', newMnemonic);
      await storage.setItem('userAddress', address);
      setAddress(address);
      setAuthenticated(true);
      setMnemonic(newMnemonic);

      // ✅ Сохраняем nonce из ответа сервера (если есть)
      if (registerData.nonce) {
        await storage.setItem('nonce', registerData.nonce);
      } else {
        // fallback – если сервер не вернул nonce, запрашиваем отдельно
        console.warn('Nonce not in response, fetching separately...');
        try {
          const nonceRes = await fetch(`${API_BASE_URL}/nonce`);
          if (nonceRes.ok) {
            const nonceData = await nonceRes.json();
            await storage.setItem('nonce', nonceData.nonce);
          }
        } catch (e) {
          console.warn('Nonce fetch failed:', e);
        }
      }

      // Сохраняем зашифрованную мнемонику, если выбран локальный пароль
      if (saveLocally && password) {
        try {
          const { encryptMnemonic, saveEncryptedMnemonic } = await import('../utils/secureStorage');
          const encrypted = await encryptMnemonic(newMnemonic, password);
          if (encrypted) await saveEncryptedMnemonic(encrypted);
        } catch (encryptError) {
          console.error('Encryption error:', encryptError);
          Alert.alert('Warning', 'Failed to encrypt mnemonic. You will need to enter it manually next time.');
        }
      }

      Alert.alert(
        'Wallet created',
        `Your address: ${address}\n\nSave your mnemonic safely!`,
        [{ text: 'OK' }]
      );

      // Инициализируем WebSocket
      await initWebSocket();
      startHeartbeat();
      startStatusPolling();
      startUserStatusPolling();

      navigation.replace('Main');
    } catch (error) {
      console.error('Create wallet error:', error);
      Alert.alert('Error', error.message || 'Failed to create wallet');
    } finally {
      setLoading(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <BlurView intensity={20} tint="dark" style={[styles.card, glassStyle]}>
        <Text style={styles.title}>Create New Wallet</Text>
        <Text style={styles.subtitle}>Generate a new 24-word recovery phrase</Text>

        {mnemonic && (
          <View style={styles.mnemonicBox}>
            <Text style={styles.mnemonicText}>{mnemonic}</Text>
          </View>
        )}

        <View style={styles.switchRow}>
          <Switch
            value={saveLocally}
            onValueChange={setSaveLocally}
            trackColor={{ false: '#2a2a2a', true: colors.accent }}
            thumbColor={saveLocally ? '#fff' : '#f4f3f4'}
          />
          <Text style={styles.switchLabel}>Save locally (with password)</Text>
        </View>

        {saveLocally && (
          <>
            <TextInput
              style={styles.input}
              placeholder="Encryption password"
              placeholderTextColor={colors.textMuted}
              secureTextEntry
              value={password}
              onChangeText={setPassword}
            />
            <TextInput
              style={styles.input}
              placeholder="Confirm password"
              placeholderTextColor={colors.textMuted}
              secureTextEntry
              value={confirmPassword}
              onChangeText={setConfirmPassword}
            />
          </>
        )}

        <OvalButton
          title="Generate Wallet"
          primary
          loading={loading}
          onPress={generateWallet}
          style={styles.fullWidth}
        />
      </BlurView>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  content: {
    flexGrow: 1,
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
    marginBottom: 24,
    textAlign: 'center',
  },
  mnemonicBox: {
    backgroundColor: 'rgba(0,0,0,0.3)',
    padding: 16,
    borderRadius: 16,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: colors.glassBorder,
  },
  mnemonicText: {
    color: colors.textMain,
    fontSize: 16,
    textAlign: 'center',
    fontFamily: 'monospace',
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
    gap: 12,
  },
  switchLabel: {
    color: colors.textMuted,
    fontSize: 14,
    flexShrink: 1,
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
});