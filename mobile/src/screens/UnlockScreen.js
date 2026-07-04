// src/screens/UnlockScreen.js
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  Alert,
  ActivityIndicator,
  Animated,
  Keyboard,
  TouchableWithoutFeedback,
  Vibration,
  TouchableOpacity,
  AppState,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import * as LocalAuthentication from 'expo-local-authentication';
import * as SecureStore from 'expo-secure-store';
import { colors, glassStyle } from '../theme';
import { OvalButton } from '../components/OvalButton';
import useUserStore from '../store/userStore';
import { decryptMnemonic, clearEncryptedMnemonic, hasEncryptedMnemonic } from '../utils/secureStorage';
import DarkCrypto from '../shared/rn_crypto-client';
import { storage } from '../utils/storage';
import { API_BASE_URL } from '../config/constants';
import { initWebSocket, startHeartbeat, startStatusPolling, startUserStatusPolling } from '../shared/rn_core';

const MAX_ATTEMPTS = 5;
const LOCKOUT_DURATION_MS = 30000;
const BIOMETRIC_PASSWORD_KEY = 'biometric_auth_password';

export default function UnlockScreen({ navigation }) {
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [attempts, setAttempts] = useState(0);
  const [isLocked, setIsLocked] = useState(false);
  const [lockoutTimer, setLockoutTimer] = useState(0);
  const [biometricAvailable, setBiometricAvailable] = useState(false);
  const [biometricType, setBiometricType] = useState(null);
  const [hasBiometricPassword, setHasBiometricPassword] = useState(false);
  const [usePinMode, setUsePinMode] = useState(false);
  const [pin, setPin] = useState('');

  const { encryptedMnemonic, setAddress, setAuthenticated, setNeedsUnlock } = useUserStore();
  const shakeAnim = useRef(new Animated.Value(0)).current;
  const lockoutIntervalRef = useRef(null);
  const appStateRef = useRef(AppState.currentState);

  // ===== 1. Инициализация при монтировании =====
  useEffect(() => {
    checkBiometricSetup();
    checkEncryptedMnemonicExists();
    loadAttemptsFromStorage();

    // Отслеживаем возврат из фона — сбрасываем биометрию
    const subscription = AppState.addEventListener('change', nextAppState => {
      if (appStateRef.current.match(/inactive|background/) && nextAppState === 'active') {
        // Приложение вернулось из фона — можно запросить биометрию снова
        if (biometricAvailable && !isLocked && !loading) {
          attemptBiometricUnlock();
        }
      }
      appStateRef.current = nextAppState;
    });

    return () => {
      subscription.remove();
      if (lockoutIntervalRef.current) clearInterval(lockoutIntervalRef.current);
    };
  }, []);

  // ===== 2. Проверка биометрии и сохранённого пароля =====
  const checkBiometricSetup = async () => {
    try {
      const compatible = await LocalAuthentication.hasHardwareAsync();
      const enrolled = await LocalAuthentication.isEnrolledAsync();

      if (compatible && enrolled) {
        const types = await LocalAuthentication.supportedAuthenticationTypesAsync();
        setBiometricAvailable(true);

        if (types.includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION)) {
          setBiometricType('face');
        } else if (types.includes(LocalAuthentication.AuthenticationType.FINGERPRINT)) {
          setBiometricType('fingerprint');
        } else {
          setBiometricType('biometric');
        }

        // Проверяем, сохранял ли пользователь пароль для биометрии
        const savedPassword = await SecureStore.getItemAsync(BIOMETRIC_PASSWORD_KEY);
        setHasBiometricPassword(!!savedPassword);

        // Автопопытка биометрии через 800мс (чтобы экран успел появиться)
        if (savedPassword) {
          setTimeout(() => attemptBiometricUnlock(), 800);
        }
      }
    } catch (e) {
      console.log('[Unlock] Biometric check failed:', e);
    }
  };

  const checkEncryptedMnemonicExists = async () => {
    const hasEncrypted = await hasEncryptedMnemonic();
    if (!hasEncrypted && !encryptedMnemonic) {
      Alert.alert(
        'No Encrypted Wallet',
        'No encrypted wallet found. Please log in with your mnemonic phrase.',
        [{ text: 'Go to Login', onPress: () => navigation.replace('Login') }]
      );
    }
  };

  const loadAttemptsFromStorage = async () => {
    const savedAttempts = await storage.getItem('unlock_attempts');
    const savedLockoutEnd = await storage.getItem('lockout_end_time');

    if (savedLockoutEnd) {
      const endTime = parseInt(savedLockoutEnd);
      const now = Date.now();
      if (now < endTime) {
        const remainingSeconds = Math.ceil((endTime - now) / 1000);
        setIsLocked(true);
        setLockoutTimer(remainingSeconds);
        startLockoutTimer(remainingSeconds);
      } else {
        await storage.removeItem('lockout_end_time');
        setAttempts(parseInt(savedAttempts) || 0);
      }
    } else {
      setAttempts(parseInt(savedAttempts) || 0);
    }
  };

  // ===== 3. Анимация тряски =====
  const shake = useCallback(() => {
    Vibration.vibrate([0, 50, 50, 50]);
    Animated.sequence([
      Animated.timing(shakeAnim, { toValue: 12, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: -12, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: 10, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: -10, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: 6, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: -6, duration: 60, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: 0, duration: 60, useNativeDriver: true }),
    ]).start();
  }, [shakeAnim]);

  // ===== 4. Блокировка =====
  const startLockoutTimer = (seconds) => {
    setLockoutTimer(seconds);

    lockoutIntervalRef.current = setInterval(async () => {
      setLockoutTimer(prev => {
        if (prev <= 1) {
          clearInterval(lockoutIntervalRef.current);
          setIsLocked(false);
          setAttempts(0);
          storage.removeItem('unlock_attempts');
          storage.removeItem('lockout_end_time');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const triggerLockout = useCallback(async () => {
    setIsLocked(true);
    const endTime = Date.now() + LOCKOUT_DURATION_MS;
    await storage.setItem('lockout_end_time', endTime.toString());
    startLockoutTimer(LOCKOUT_DURATION_MS / 1000);
  }, []);

  // ===== 5. Биометрическая разблокировка =====
  const attemptBiometricUnlock = async () => {
    if (!biometricAvailable || isLocked || loading) return;

    try {
      const result = await LocalAuthentication.authenticateAsync({
        promptMessage: 'Unlock Dark Messenger',
        fallbackLabel: 'Use password instead',
        cancelLabel: 'Cancel',
        disableDeviceFallback: true,
      });

      if (result.success) {
        // Получаем сохранённый пароль из SecureStore
        const savedPassword = await SecureStore.getItemAsync(BIOMETRIC_PASSWORD_KEY);
        if (savedPassword) {
          setPassword(savedPassword);
          // Автоматически разблокируем с сохранённым паролем
          await performUnlock(savedPassword, true);
        } else {
          // Первый раз — просим ввести пароль и предлагаем сохранить
          Alert.alert(
            'Biometric Auth',
            'Enter your password once to enable biometric unlock in the future.',
            [{ text: 'OK' }]
          );
        }
      }
    } catch (e) {
      console.log('[Unlock] Biometric error:', e);
    }
  };

  // ===== 6. Сохранение пароля для биометрии =====
  const savePasswordForBiometric = async (pwd) => {
    try {
      await SecureStore.setItemAsync(BIOMETRIC_PASSWORD_KEY, pwd, {
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      });
      setHasBiometricPassword(true);
    } catch (e) {
      console.warn('Failed to save biometric password:', e);
    }
  };

  // ===== 7. Основная логика разблокировки =====
  const performUnlock = async (pwd, fromBiometric = false) => {
    if (!pwd.trim()) {
      shake();
      return { success: false, error: 'empty' };
    }

    if (isLocked) {
      return { success: false, error: 'locked' };
    }

    setLoading(true);
    Keyboard.dismiss();

    try {
      const mnemonic = await decryptMnemonic(encryptedMnemonic, pwd);

      if (!mnemonic) {
        const newAttempts = attempts + 1;
        setAttempts(newAttempts);
        await storage.setItem('unlock_attempts', newAttempts.toString());

        shake();

        if (newAttempts >= MAX_ATTEMPTS) {
          await triggerLockout();
          setLoading(false);
          return { success: false, error: 'max_attempts' };
        }

        setLoading(false);
        return { success: false, error: 'wrong_password' };
      }

      // ✅ УСПЕХ
      setAttempts(0);
      await storage.removeItem('unlock_attempts');
      await storage.removeItem('lockout_end_time');
      Vibration.vibrate([0, 80, 50, 80]);

      // Если разблокировали через пароль (не биометрию) и биометрия доступна — предлагаем сохранить
      if (!fromBiometric && biometricAvailable && !hasBiometricPassword) {
        // Сохраняем автоматически для удобства
        await savePasswordForBiometric(pwd);
      }

      const keys = await DarkCrypto.deriveKeyPair(mnemonic);
      const { address } = keys;

      await storage.setItem('mnemonic', mnemonic);
      await storage.setItem('userAddress', address);
      setAddress(address);
      setAuthenticated(true);
      setNeedsUnlock(false, null);

      // Получаем nonce
      let nonce = await storage.getItem('nonce');
      if (!nonce) {
        try {
          const nonceRes = await fetch(`${API_BASE_URL}/nonce`);
          if (nonceRes.ok) {
            const nonceData = await nonceRes.json();
            nonce = nonceData.nonce;
            await storage.setItem('nonce', nonce);
          }
        } catch (e) {
          console.warn('Nonce fetch failed:', e);
        }
      }

      // Инициализация WebSocket
      await initWebSocket();
      startHeartbeat();
      startStatusPolling();
      startUserStatusPolling();

      setLoading(false);
      return { success: true, address };

    } catch (error) {
      console.error('[Unlock] Error:', error);
      shake();
      setLoading(false);
      return { success: false, error: 'unknown' };
    }
  };

  const handleUnlock = async () => {
    const result = await performUnlock(password);

    if (result.success) {
      navigation.replace('Main');
    } else if (result.error === 'max_attempts') {
      Alert.alert(
        '🔒 Too Many Attempts',
        `Your wallet is temporarily locked. Please wait ${LOCKOUT_DURATION_MS / 1000} seconds before trying again.`,
        [{ text: 'OK' }]
      );
      setPassword('');
    } else if (result.error === 'wrong_password') {
      Alert.alert(
        '❌ Wrong Password',
        `Attempt ${attempts + 1} of ${MAX_ATTEMPTS}. Please try again.`,
        [{ text: 'OK' }]
      );
      setPassword('');
    } else if (result.error === 'locked') {
      Alert.alert('🔒 Locked', `Please wait ${lockoutTimer} seconds.`);
    }
  };

  // ===== 8. PIN-код режим =====
  const handlePinUnlock = async () => {
    if (pin.length !== 6) {
      shake();
      return;
    }
    // PIN — это просто короткий пароль, используем тот же механизм
    const result = await performUnlock(pin);
    if (result.success) {
      navigation.replace('Main');
    } else {
      setPin('');
      shake();
    }
  };

  // ===== 9. Логаут =====
  const handleLogout = () => {
    Alert.alert(
      '🚪 Log Out',
      'This will permanently delete your encrypted wallet from this device. You will need to enter your 24-word mnemonic phrase to log in again.\n\nAre you sure?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Log Out',
          style: 'destructive',
          onPress: async () => {
            await clearEncryptedMnemonic();
            await SecureStore.deleteItemAsync(BIOMETRIC_PASSWORD_KEY);
            await storage.removeItem('unlock_attempts');
            await storage.removeItem('lockout_end_time');
            setNeedsUnlock(false, null);
            navigation.replace('Login');
          },
        },
      ]
    );
  };

  const handleForgotPassword = () => {
    Alert.alert(
      'Forgot Password?',
      'Your encrypted wallet can only be unlocked with the correct password.\n\nYou have two options:\n\n1. Try to remember your password\n2. Log out and restore your wallet using your 24-word mnemonic phrase',
      [
        { text: 'Try Again', style: 'cancel' },
        { text: 'Log Out', style: 'destructive', onPress: handleLogout },
      ]
    );
  };

  const getBiometricIcon = () => {
    if (biometricType === 'face') return 'scan-outline';
    if (biometricType === 'fingerprint') return 'finger-print-outline';
    return 'lock-open-outline';
  };

  const getBiometricLabel = () => {
    if (biometricType === 'face') return 'Use Face ID';
    if (biometricType === 'fingerprint') return 'Use Fingerprint';
    return 'Use Biometrics';
  };

  // ===== RENDER =====
  return (
    <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
      <View style={styles.container}>
        <BlurView intensity={20} tint="dark" style={[styles.card, glassStyle]}>

          {/* Логотип */}
          <View style={styles.logoContainer}>
            <Ionicons name="shield-checkmark" size={40} color={colors.accent} />
          </View>

          <Text style={styles.title}>🔐 Unlock Wallet</Text>
          <Text style={styles.subtitle}>
            Your encrypted wallet was found.{'\n'}Enter password to unlock.
          </Text>

          {/* Биометрическая кнопка */}
          {biometricAvailable && hasBiometricPassword && !isLocked && (
            <TouchableOpacity
              style={styles.biometricBtn}
              onPress={attemptBiometricUnlock}
              activeOpacity={0.8}
            >
              <Ionicons name={getBiometricIcon()} size={32} color={colors.accent} />
              <Text style={styles.biometricText}>{getBiometricLabel()}</Text>
            </TouchableOpacity>
          )}

          {/* Переключатель PIN / Password */}
          <View style={styles.modeToggle}>
            <TouchableOpacity
              style={[styles.modeBtn, !usePinMode && styles.modeBtnActive]}
              onPress={() => { setUsePinMode(false); setPin(''); }}
            >
              <Text style={[styles.modeText, !usePinMode && styles.modeTextActive]}>Password</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.modeBtn, usePinMode && styles.modeBtnActive]}
              onPress={() => { setUsePinMode(true); setPassword(''); }}
            >
              <Text style={[styles.modeText, usePinMode && styles.modeTextActive]}>PIN</Text>
            </TouchableOpacity>
          </View>

          {/* Поле ввода с анимацией тряски */}
          <Animated.View style={{ transform: [{ translateX: shakeAnim }], width: '100%' }}>
            {!usePinMode ? (
              <View style={styles.inputWrapper}>
                <TextInput
                  style={[styles.input, isLocked && styles.inputLocked]}
                  placeholder="Enter password"
                  placeholderTextColor={colors.textMuted}
                  secureTextEntry={!showPassword}
                  value={password}
                  onChangeText={setPassword}
                  autoFocus
                  editable={!isLocked}
                  onSubmitEditing={handleUnlock}
                  returnKeyType="done"
                  textContentType="password"
                />
                <TouchableOpacity
                  style={styles.eyeBtn}
                  onPress={() => setShowPassword(!showPassword)}
                  hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                >
                  <Ionicons
                    name={showPassword ? 'eye-off-outline' : 'eye-outline'}
                    size={20}
                    color={colors.textMuted}
                  />
                </TouchableOpacity>
              </View>
            ) : (
              <View style={styles.pinContainer}>
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <View key={i} style={[
                    styles.pinDot,
                    pin.length > i && styles.pinDotFilled,
                    isLocked && styles.pinDotLocked
                  ]} />
                ))}
                <TextInput
                  style={styles.pinInput}
                  value={pin}
                  onChangeText={(text) => {
                    if (text.length <= 6 && /^\d*$/.test(text)) {
                      setPin(text);
                      if (text.length === 6) {
                        setTimeout(() => handlePinUnlock(), 100);
                      }
                    }
                  }}
                  keyboardType="number-pad"
                  maxLength={6}
                  secureTextEntry
                  editable={!isLocked}
                  autoFocus
                />
              </View>
            )}
          </Animated.View>

          {/* Индикатор блокировки */}
          {isLocked && (
            <View style={styles.lockoutBanner}>
              <Ionicons name="time-outline" size={18} color={colors.danger} />
              <Text style={styles.lockoutText}>
                🔒 Locked. Try again in {lockoutTimer}s
              </Text>
            </View>
          )}

          {/* Индикатор попыток */}
          {!isLocked && attempts > 0 && (
            <View style={styles.attemptsContainer}>
              <View style={styles.attemptsBar}>
                {Array.from({ length: MAX_ATTEMPTS }).map((_, i) => (
                  <View key={i} style={[
                    styles.attemptDot,
                    i < attempts && styles.attemptDotUsed
                  ]} />
                ))}
              </View>
              <Text style={styles.attemptsText}>
                Attempt {attempts} of {MAX_ATTEMPTS}
              </Text>
            </View>
          )}

          {/* Кнопка разблокировки */}
          {!usePinMode && (
            <OvalButton
              title={loading ? 'Unlocking…' : '🔓 Unlock Wallet'}
              primary
              loading={loading}
              onPress={handleUnlock}
              style={[styles.fullWidth, (isLocked || loading) && styles.disabledBtn]}
              disabled={loading || isLocked || !password.trim()}
            />
          )}

          {/* Дополнительные действия */}
          <View style={styles.footerActions}>
            <TouchableOpacity onPress={handleForgotPassword}>
              <Text style={styles.footerLink}>Forgot password?</Text>
            </TouchableOpacity>

            <View style={styles.divider} />

            <TouchableOpacity onPress={handleLogout}>
              <Text style={[styles.footerLink, styles.dangerLink]}>
                🚪 Log out & clear data
              </Text>
            </TouchableOpacity>
          </View>

          {/* Security note */}
          <Text style={styles.securityNote}>
            🔒 Your keys never leave this device
          </Text>
        </BlurView>
      </View>
    </TouchableWithoutFeedback>
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
    padding: 28,
    ...glassStyle,
  },
  logoContainer: {
    alignItems: 'center',
    marginBottom: 20,
    width: 80,
    height: 80,
    borderRadius: 24,
    backgroundColor: 'rgba(108, 92, 231, 0.15)',
    justifyContent: 'center',
    alignSelf: 'center',
    borderWidth: 1,
    borderColor: 'rgba(108, 92, 231, 0.3)',
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: colors.textMain,
    marginBottom: 8,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 15,
    color: colors.textMuted,
    marginBottom: 24,
    textAlign: 'center',
    lineHeight: 22,
  },
  biometricBtn: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 16,
    marginBottom: 16,
    backgroundColor: 'rgba(108, 92, 231, 0.1)',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: 'rgba(108, 92, 231, 0.2)',
  },
  biometricText: {
    color: colors.accent,
    fontSize: 14,
    fontWeight: '600',
    marginTop: 8,
  },
  inputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
    position: 'relative',
  },
  input: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.3)',
    borderWidth: 1,
    borderColor: colors.glassBorder,
    borderRadius: 50,
    paddingHorizontal: 16,
    paddingVertical: 12,
    paddingRight: 48, // место для иконки глаза
    color: colors.textMain,
    fontSize: 16,
  },
  inputLocked: {
    borderColor: colors.danger,
    opacity: 0.6,
  },
  eyeBtn: {
    position: 'absolute',
    right: 12,
    padding: 4,
  },
  lockoutBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: 'rgba(214, 48, 49, 0.1)',
    borderRadius: 12,
    paddingVertical: 10,
    paddingHorizontal: 16,
    marginBottom: 12,
  },
  lockoutText: {
    color: colors.danger,
    fontSize: 13,
    fontWeight: '600',
  },
  attemptsText: {
    color: colors.danger,
    fontSize: 12,
    textAlign: 'center',
    marginBottom: 12,
    opacity: 0.8,
  },
  fullWidth: {
    width: '100%',
    marginTop: 4,
  },
  disabledBtn: {
    opacity: 0.4,
  },
  footerActions: {
    marginTop: 20,
    alignItems: 'center',
    gap: 12,
  },
  divider: {
    width: 40,
    height: 1,
    backgroundColor: 'rgba(255,255,255,0.1)',
    marginVertical: 4,
  },
  footerLink: {
    color: colors.textMuted,
    fontSize: 14,
  },
  dangerLink: {
    color: colors.danger,
  },
});