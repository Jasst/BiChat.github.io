import React, { useState, useEffect } from 'react';
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
} from 'react-native';
import { Camera, useCameraPermissions } from 'expo-camera';
import { Ionicons } from '@expo/vector-icons';
import { parseQRData } from '../utils/QRManager';

export default function QRScannerModal({ visible, onClose, onScan, title = 'Scan QR Code' }) {
  const [permission, requestPermission] = useCameraPermissions();
  const [scanned, setScanned] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (visible) {
      setScanned(false);
      setError(null);
      if (!permission) {
        requestPermission();
      }
    }
  }, [visible]);

  const handleBarCodeScanned = ({ type, data }) => {
    setScanned(true);
    const address = parseQRData(data);
    if (address) {
      onScan?.(address);
      onClose();
    } else {
      setError('Invalid QR code');
      setTimeout(() => {
        setScanned(false);
        setError(null);
      }, 2000);
    }
  };

  if (!visible) return null;

  if (!permission) {
    return (
      <Modal visible={visible} transparent animationType="slide">
        <View style={styles.centered}>
          <ActivityIndicator size="large" color="#6c5ce7" />
          <Text style={styles.text}>Requesting camera permission...</Text>
        </View>
      </Modal>
    );
  }

  if (!permission.granted) {
    return (
      <Modal visible={visible} transparent animationType="slide">
        <View style={styles.centered}>
          <Ionicons name="camera-off" size={64} color="#d63031" />
          <Text style={[styles.text, { color: '#d63031', marginTop: 16 }]}>No camera access</Text>
          <TouchableOpacity style={styles.closeButton} onPress={onClose}>
            <Text style={styles.closeText}>Close</Text>
          </TouchableOpacity>
        </View>
      </Modal>
    );
  }

  return (
    <Modal visible={visible} transparent animationType="slide">
      <View style={styles.container}>
        <Camera
          style={StyleSheet.absoluteFillObject}
          onBarcodeScanned={scanned ? undefined : handleBarCodeScanned}
          barcodeScannerSettings={{
            barcodeTypes: ['qr'],
          }}
        />
        <View style={styles.overlay}>
          <View style={styles.header}>
            <Text style={styles.headerTitle}>{title}</Text>
            <TouchableOpacity onPress={onClose}>
              <Ionicons name="close" size={28} color="#fff" />
            </TouchableOpacity>
          </View>
          <View style={styles.scanFrame} />
          {error && (
            <View style={styles.errorContainer}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}
          <Text style={styles.instruction}>Align QR code in the frame</Text>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: 'black' },
  overlay: { flex: 1, justifyContent: 'center', alignItems: 'center', paddingTop: 40 },
  header: {
    position: 'absolute',
    top: 40,
    left: 20,
    right: 20,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    zIndex: 10,
  },
  headerTitle: { color: '#fff', fontSize: 18, fontWeight: '600' },
  scanFrame: { width: 280, height: 280, borderWidth: 2, borderColor: '#6c5ce7', borderRadius: 12 },
  instruction: {
    position: 'absolute',
    bottom: 60,
    color: '#fff',
    fontSize: 16,
    backgroundColor: 'rgba(0,0,0,0.6)',
    paddingHorizontal: 20,
    paddingVertical: 8,
    borderRadius: 20,
  },
  centered: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#0a0a0a' },
  text: { color: '#fff', fontSize: 16, marginTop: 12 },
  closeButton: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 10, borderRadius: 50, backgroundColor: '#6c5ce7' },
  closeText: { color: '#fff', fontWeight: 'bold' },
  errorContainer: { position: 'absolute', top: 100, backgroundColor: 'rgba(214, 48, 49, 0.9)', paddingHorizontal: 16, paddingVertical: 8, borderRadius: 8 },
  errorText: { color: '#fff', fontWeight: 'bold' },
});