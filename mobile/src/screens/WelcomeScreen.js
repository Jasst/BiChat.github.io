// src/screens/WelcomeScreen.js
import React, { useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Image,
  Animated,
  Dimensions,
  StatusBar,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import { colors, glassStyle } from '../theme';
import { OvalButton } from '../components/OvalButton';
import { Ionicons } from '@expo/vector-icons';
import useUserStore from '../store/userStore';

const { width, height } = Dimensions.get('window');

export default function WelcomeScreen() {
  const navigation = useNavigation();
  const { isAuthenticated, address } = useUserStore();

  // Анимации
  const fadeAnim = React.useRef(new Animated.Value(0)).current;
  const slideAnim = React.useRef(new Animated.Value(50)).current;
  const scaleAnim = React.useRef(new Animated.Value(0.9)).current;

  useEffect(() => {
    // Если уже авторизован — сразу в Main
    if (isAuthenticated && address) {
      navigation.replace('Main');
      return;
    }

    // Стартовая анимация
    Animated.parallel([
      Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 800,
        useNativeDriver: true,
      }),
      Animated.timing(slideAnim, {
        toValue: 0,
        duration: 800,
        useNativeDriver: true,
      }),
      Animated.timing(scaleAnim, {
        toValue: 1,
        duration: 800,
        useNativeDriver: true,
      }),
    ]).start();
  }, [isAuthenticated, address]);

  const handleLogin = () => {
    Animated.sequence([
      Animated.timing(scaleAnim, {
        toValue: 0.95,
        duration: 100,
        useNativeDriver: true,
      }),
      Animated.timing(scaleAnim, {
        toValue: 1,
        duration: 100,
        useNativeDriver: true,
      }),
    ]).start(() => {
      navigation.navigate('Login');
    });
  };

  const handleCreateWallet = () => {
    Animated.sequence([
      Animated.timing(scaleAnim, {
        toValue: 0.95,
        duration: 100,
        useNativeDriver: true,
      }),
      Animated.timing(scaleAnim, {
        toValue: 1,
        duration: 100,
        useNativeDriver: true,
      }),
    ]).start(() => {
      navigation.navigate('CreateWallet');
    });
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" />

      {/* Фоновый градиент */}
      <LinearGradient
        colors={['#0a0a0f', '#1a1a2e', '#0a0a0f']}
        style={styles.gradient}
      />

      {/* Декоративные круги */}
      <View style={[styles.glowCircle, styles.glowCircle1]} />
      <View style={[styles.glowCircle, styles.glowCircle2]} />

      <Animated.View
        style={[
          styles.content,
          {
            opacity: fadeAnim,
            transform: [
              { translateY: slideAnim },
              { scale: scaleAnim },
            ],
          },
        ]}
      >
        {/* Логотип */}
        <View style={styles.logoContainer}>
          <View style={styles.logo}>
            <Ionicons name="shield-checkmark" size={48} color={colors.accent} />
          </View>
          <View style={styles.logoRing} />
        </View>

        {/* Заголовок */}
        <Text style={styles.title}>Dark Messenger</Text>
        <Text style={styles.subtitle}>Decentralized • Encrypted • Secure</Text>

        {/* Описание */}
        <View style={styles.features}>
          <View style={styles.featureItem}>
            <Ionicons name="lock-closed" size={16} color={colors.accent} />
            <Text style={styles.featureText}>End-to-end encryption</Text>
          </View>
          <View style={styles.featureItem}>
            <Ionicons name="git-network" size={16} color={colors.accent} />
            <Text style={styles.featureText}>Decentralized network</Text>
          </View>
          <View style={styles.featureItem}>
            <Ionicons name="wallet" size={16} color={colors.accent} />
            <Text style={styles.featureText}>Built-in crypto wallet</Text>
          </View>
        </View>

        {/* Карточка с кнопками */}
        <BlurView intensity={20} tint="dark" style={[styles.card, glassStyle]}>
          <OvalButton
            title="🔑 Login with Mnemonic"
            primary
            onPress={handleLogin}
            style={styles.fullWidth}
            icon={<Ionicons name="key" size={18} color="#fff" style={{ marginRight: 8 }} />}
          />

          <View style={styles.divider}>
            <View style={styles.dividerLine} />
            <Text style={styles.dividerText}>or</Text>
            <View style={styles.dividerLine} />
          </View>

          <OvalButton
            title="✨ Create New Wallet"
            onPress={handleCreateWallet}
            style={[styles.fullWidth, styles.outlineBtn]}
            icon={<Ionicons name="add-circle" size={18} color={colors.accent} style={{ marginRight: 8 }} />}
          />
        </BlurView>

        {/* Футер */}
        <Text style={styles.footer}>
          By continuing, you agree to our Terms of Service
        </Text>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  gradient: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
  },
  glowCircle: {
    position: 'absolute',
    borderRadius: 999,
    opacity: 0.15,
  },
  glowCircle1: {
    width: 300,
    height: 300,
    backgroundColor: colors.accent,
    top: height * 0.1,
    left: -50,
    blur: 100,
  },
  glowCircle2: {
    width: 250,
    height: 250,
    backgroundColor: '#00b894',
    bottom: height * 0.15,
    right: -30,
  },
  content: {
    width: '100%',
    paddingHorizontal: 30,
    alignItems: 'center',
  },
  logoContainer: {
    width: 100,
    height: 100,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 24,
  },
  logo: {
    width: 80,
    height: 80,
    borderRadius: 24,
    backgroundColor: 'rgba(108, 92, 231, 0.15)',
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(108, 92, 231, 0.3)',
  },
  logoRing: {
    position: 'absolute',
    width: 100,
    height: 100,
    borderRadius: 30,
    borderWidth: 2,
    borderColor: 'rgba(108, 92, 231, 0.2)',
  },
  title: {
    fontSize: 36,
    fontWeight: 'bold',
    color: colors.textMain,
    marginBottom: 8,
    textAlign: 'center',
    letterSpacing: -0.5,
  },
  subtitle: {
    fontSize: 16,
    color: colors.textMuted,
    marginBottom: 32,
    textAlign: 'center',
    letterSpacing: 0.5,
  },
  features: {
    alignItems: 'flex-start',
    marginBottom: 32,
    gap: 10,
  },
  featureItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  featureText: {
    color: colors.textMuted,
    fontSize: 14,
  },
  card: {
    width: '100%',
    maxWidth: 400,
    padding: 28,
    alignItems: 'center',
    borderRadius: 24,
    ...glassStyle,
  },
  fullWidth: {
    width: '100%',
    marginBottom: 0,
  },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    width: '100%',
    marginVertical: 20,
    gap: 12,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: 'rgba(255,255,255,0.1)',
  },
  dividerText: {
    color: colors.textMuted,
    fontSize: 13,
    fontWeight: '500',
  },
  outlineBtn: {
    borderColor: colors.accent,
    borderWidth: 1.5,
    backgroundColor: 'transparent',
  },
  footer: {
    color: 'rgba(255,255,255,0.3)',
    fontSize: 12,
    marginTop: 24,
    textAlign: 'center',
  },
});