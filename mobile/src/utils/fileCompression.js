// src/utils/fileCompression.js
import * as ImageManipulator from 'expo-image-manipulator';

/**
 * Сжатие изображения (работает в Expo Go)
 * @param {string} uri - URI исходного файла
 * @param {number} maxWidth - максимальная ширина (соотношение сохраняется)
 * @param {number} quality - качество JPEG (0-1)
 * @returns {Promise<{uri: string, type: string, name: string}>}
 */
export async function compressImageFile(uri, maxWidth = 1024, quality = 0.7) {
  const result = await ImageManipulator.manipulateAsync(
    uri,
    [{ resize: { width: maxWidth } }],
    { compress: quality, format: ImageManipulator.SaveFormat.JPEG }
  );
  return {
    uri: result.uri,
    type: 'image/jpeg',
    name: 'image.jpg',
  };
}

/**
 * Сжатие видео – в Expo Go не поддерживается нативными модулями,
 * поэтому возвращаем оригинал без изменений.
 * @param {string} uri - URI исходного видео
 * @returns {Promise<{uri: string, type: string, name: string}>}
 */
export async function compressVideoFile(uri, quality = 'medium') {
  console.warn('Video compression is not available in Expo Go. Returning original file.');
  // Определяем имя из URI (если возможно)
  const name = uri.split('/').pop() || 'video.mp4';
  // Определяем тип по расширению или оставляем общий
  const type = 'video/mp4';
  return { uri, type, name };
}

/**
 * Универсальная подготовка файла перед отправкой
 * – изображения сжимаются
 * – видео и прочие файлы возвращаются как есть
 */
export async function prepareFileForUpload(file) {
  if (!file) return file;
  if (file.type?.startsWith('image/')) {
    return await compressImageFile(file.uri);
  }
  // Для видео и других типов – без изменений
  return file;
}