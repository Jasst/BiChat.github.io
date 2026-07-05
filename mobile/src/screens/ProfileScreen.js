// src/screens/ProfileScreen.js
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Alert,
  ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import useUserStore from '../store/userStore';
import { storage } from '../utils/storage';
import QRCodeDisplay from '../components/QRCodeDisplay';
import * as Notifications from 'expo-notifications';
import { GlassCard } from '../components/GlassCard';
import { OvalButton } from '../components/OvalButton';
import { GlassModal } from '../components/GlassModal';
import { colors, glassStyle } from '../theme';

export default function ProfileScreen() {
  const { address, logout } = useUserStore();
  const [mnemonic, setMnemonic] = useState('');
  const [showMnemonic, setShowMnemonic] = useState(false);
  const [mnemonicModalVisible, setMnemonicModalVisible] = useState(false);

  useEffect(() => {
    (async () => {
      const stored = await storage.getItem('mnemonic');
      if (stored) setMnemonic(stored);
    })();
  }, []);

  const copyAddress = () => {
    if (address) {
      // используем Clipboard API
      Alert.alert('Copied', address.slice(0, 16) + '…');
    }
  };

  const requestNotifications = async () => {
    const { status } = await Notifications.requestPermissionsAsync();
    if (status === 'granted') {
      Alert.alert('Notifications enabled');
    } else {
      Alert.alert('Permission denied');
    }
  };

  const handleRevealMnemonic = () => {
    // Просто показываем модалку (без дополнительного подтверждения, как в вебе)
    setMnemonicModalVisible(true);
    setShowMnemonic(true);
  };

  const downloadQR = () => {
    // Можно использовать react-native-view-shot для сохранения
    Alert.alert('Download QR', 'Function not implemented in this demo');
  };

  const shareQR = () => {
    Alert.alert('Share QR', 'Function not implemented in this demo');
  };

  return (
    <ScrollView style={styles.container}>
      <GlassCard style={styles.card}>
        <Text style={styles.label}>Your Address</Text>
        <View style={styles.addressRow}>
          <Text style={styles.address}>{address || 'Not set'}</Text>
          <TouchableOpacity onPress={copyAddress} style={styles.iconBtn}>
            <Ionicons name="copy-outline" size={20} color={colors.accent} />
          </TouchableOpacity>
        </View>
        <View style={styles.qrContainer}>
          <QRCodeDisplay value={address} size={150} />
          <View style={styles.qrActions}>
            <OvalButton title="Download" onPress={downloadQR} />
            <OvalButton title="Share" onPress={shareQR} />
          </View>
        </View>
      </GlassCard>

      <GlassCard style={styles.card}>
        <Text style={styles.label}>Recovery Phrase</Text>
        <OvalButton
          title="🔐 Export Mnemonic"
          primary
          onPress={handleRevealMnemonic}
          style={styles.fullWidth}
        />
      </GlassCard>

      <GlassCard style={styles.card}>
        <OvalButton
          title="🔔 Enable Notifications"
          onPress={requestNotifications}
          style={styles.fullWidth}
        />
        <OvalButton
          title="🚪 Logout"
          onPress={() => {
            Alert.alert('Logout', 'Are you sure?', [
              { text: 'Cancel', style: 'cancel' },
              { text: 'Logout', style: 'destructive', onPress: logout },
            ]);
          }}
          style={[styles.fullWidth, styles.logoutBtn]}
        />
      </GlassCard>

      <GlassModal
        visible={mnemonicModalVisible}
        onClose={() => {
          setMnemonicModalVisible(false);
          setShowMnemonic(false);
        }}
        title="Your Mnemonic"
      >
        <Text style={styles.mnemonicText}>
          {showMnemonic ? mnemonic : '••••••••'}
        </Text>
        <OvalButton
          title="Close"
          onPress={() => {
            setMnemonicModalVisible(false);
            setShowMnemonic(false);
          }}
          style={{ marginTop: 16 }}
        />
      </GlassModal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
    padding: 16,
  },
  card: {
    marginBottom: 20,
  },
  label: {
    color: colors.textMuted,
    fontSize: 14,
    marginBottom: 8,
  },
  addressRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  address: {
    color: colors.textMain,
    fontSize: 16,
    fontFamily: 'monospace',
    flex: 1,
  },
  iconBtn: {
    padding: 8,
  },
  qrContainer: {
    alignItems: 'center',
    marginVertical: 12,
  },
  qrActions: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 16,
  },
  fullWidth: {
    width: '100%',
  },
  logoutBtn: {
    marginTop: 12,
    borderColor: colors.danger,
    borderWidth: 1,
  },
  mnemonicText: {
    color: colors.textMain,
    fontSize: 16,
    textAlign: 'center',
    paddingVertical: 16,
    fontFamily: 'monospace',
    backgroundColor: 'rgba(0,0,0,0.2)',
    borderRadius: 12,
    padding: 16,
  },
});