// src/components/GlassCard.js
import React from 'react';
import { View, StyleSheet } from 'react-native';
import { BlurView } from 'expo-blur';
import { colors, glassStyle } from '../theme';

export const GlassCard = ({ children, style, intensity = 20, ...props }) => (
  <View style={[styles.wrapper, style]} {...props}>
    <BlurView intensity={intensity} tint="dark" style={styles.blur}>
      {children}
    </BlurView>
  </View>
);

const styles = StyleSheet.create({
  wrapper: {
    ...glassStyle,
    backgroundColor: 'transparent',
  },
  blur: {
    flex: 1,
    padding: 24,
    borderRadius: 24,
    overflow: 'hidden',
  },
});