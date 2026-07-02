// src/components/GlassModal.js
import React from 'react';
import { Modal, View, StyleSheet, TouchableOpacity, Text } from 'react-native';
import { BlurView } from 'expo-blur';
import { colors, glassStyle } from '../theme';

export const GlassModal = ({
  visible,
  onClose,
  children,
  title,
  footer,
  closeOnOverlay = true,
}) => (
  <Modal transparent visible={visible} animationType="fade">
    <BlurView intensity={10} tint="dark" style={styles.overlay}>
      <TouchableOpacity
        style={styles.overlayTouch}
        activeOpacity={1}
        onPress={closeOnOverlay ? onClose : undefined}
      >
        <View style={styles.card}>
          {title && (
            <View style={styles.header}>
              <Text style={styles.title}>{title}</Text>
              {onClose && (
                <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
                  <Text style={styles.closeText}>✕</Text>
                </TouchableOpacity>
              )}
            </View>
          )}
          <View style={styles.body}>{children}</View>
          {footer && <View style={styles.footer}>{footer}</View>}
        </View>
      </TouchableOpacity>
    </BlurView>
  </Modal>
);

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  overlayTouch: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    width: '100%',
    paddingHorizontal: 20,
  },
  card: {
    ...glassStyle,
    width: '100%',
    maxWidth: 500,
    backgroundColor: colors.glassBg,
    padding: 0,
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: colors.glassBorder,
  },
  title: {
    color: colors.textMain,
    fontSize: 18,
    fontWeight: '700',
  },
  closeBtn: {
    padding: 4,
  },
  closeText: {
    color: colors.textMuted,
    fontSize: 24,
    lineHeight: 24,
  },
  body: {
    padding: 20,
  },
  footer: {
    padding: 16,
    borderTopWidth: 1,
    borderTopColor: colors.glassBorder,
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 12,
  },
});