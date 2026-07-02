// src/theme.js
export const colors = {
  glassBg: 'rgba(20, 20, 30, 0.6)',
  glassBorder: 'rgba(255, 255, 255, 0.08)',
  accent: '#6c5ce7',
  accentGlow: 'rgba(108, 92, 231, 0.4)',
  success: '#00b894',
  danger: '#d63031',
  textMain: '#f5f6fa',
  textMuted: '#a4b0be',
  bgPrimary: '#0a0a0f',
};

export const glassStyle = {
  backgroundColor: colors.glassBg,
  borderWidth: 1,
  borderColor: colors.glassBorder,
  borderRadius: 24,
  shadowColor: '#000',
  shadowOffset: { width: 0, height: 8 },
  shadowOpacity: 0.3,
  shadowRadius: 32,
  elevation: 8,
  overflow: 'hidden',
};