import React from 'react';
import { View, StyleSheet } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

export default function QRCodeDisplay({ value, size = 200, color = '#000', backgroundColor = '#fff' }) {
  if (!value) return null;
  return (
    <View style={[styles.container, { width: size, height: size }]}>
      <QRCode value={value} size={size} color={color} backgroundColor={backgroundColor} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#fff',
    padding: 8,
    borderRadius: 12,
  },
});