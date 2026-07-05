// src/components/OvalButton.js
import React from 'react';
import { TouchableOpacity, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { colors } from '../theme';

export const OvalButton = ({
  title,
  onPress,
  primary = false,
  loading = false,
  disabled = false,
  style,
  textStyle,
  icon,
}) => (
  <TouchableOpacity
    style={[
      styles.btn,
      primary && styles.primary,
      disabled && styles.disabled,
      style,
    ]}
    onPress={onPress}
    disabled={disabled || loading}
  >
    {loading ? (
      <ActivityIndicator color={primary ? '#fff' : colors.textMain} />
    ) : (
      <>
        {icon && <Text style={styles.icon}>{icon}</Text>}
        <Text style={[styles.text, primary && styles.primaryText, textStyle]}>
          {title}
        </Text>
      </>
    )}
  </TouchableOpacity>
);

const styles = StyleSheet.create({
  btn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 50,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    borderColor: colors.glassBorder,
    minHeight: 48,
  },
  primary: {
    backgroundColor: colors.accent,
    borderWidth: 0,
    shadowColor: colors.accentGlow,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 15,
    elevation: 6,
  },
  disabled: {
    opacity: 0.5,
  },
  text: {
    color: colors.textMain,
    fontWeight: '600',
    fontSize: 14,
  },
  primaryText: {
    color: '#fff',
  },
  icon: {
    marginRight: 8,
    fontSize: 18,
  },
});