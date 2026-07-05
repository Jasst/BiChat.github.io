// src/screens/ChatDetailScreen.js
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Alert,
  ActivityIndicator,
  Modal,
  Image,
  Share,
  Keyboard,
  SafeAreaView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { useFocusEffect } from '@react-navigation/native';
import * as ImagePicker from 'expo-image-picker';
import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system/legacy';
import { colors } from '../theme';
import useChatStore from '../store/chatStore';
import useUserStore from '../store/userStore';
import { getConversation, addContact } from '../api';
import { sendMessage as sendEncryptedMessage, uploadEncryptedFile } from '../shared/rn_actions';
import { processMessageDecryption, clearMessageCache, addMessageToCache, clearDecryptionCache, getCachedMessages } from '../shared/rn_core';
import DarkCrypto from '../shared/rn_crypto-client';
import { API_BASE_URL } from '../config/constants';
import { prepareFileForUpload } from '../utils/fileCompression';

// ===================== Кэш расшифрованных изображений =====================
const decryptedImageCache = new Map();

async function decryptAndCacheImage(msg) {
  if (!msg.fileUrl || !msg.fileKey || !msg.fileIv) {
    console.log('[Image] Skip: missing fields', msg.id, { url: !!msg.fileUrl, key: !!msg.fileKey, iv: !!msg.fileIv });
    return null;
  }
  if (decryptedImageCache.has(msg.id)) return decryptedImageCache.get(msg.id);

  try {
    const fullUrl = msg.fileUrl.startsWith('http') ? msg.fileUrl : `${API_BASE_URL}${msg.fileUrl}`;
    const localPath = FileSystem.cacheDirectory + `enc_${msg.id}`;

    console.log('[Image] Downloading', msg.id, fullUrl);
    const { uri } = await FileSystem.downloadAsync(fullUrl, localPath);
    const encryptedB64 = await FileSystem.readAsStringAsync(uri, { encoding: 'base64' });
    const encryptedBytes = DarkCrypto._fromBase64(encryptedB64);

    const keyBytes = DarkCrypto._fromBase64(msg.fileKey);
    const ivBytes = DarkCrypto._fromBase64(msg.fileIv);

    console.log('[Image] Decrypting', msg.id, { enc: encryptedBytes.length, key: keyBytes.length, iv: ivBytes.length });
    const decrypted = await DarkCrypto.decryptFile(encryptedBytes, keyBytes, ivBytes);
    const decryptedB64 = DarkCrypto.arrayBufferToBase64(decrypted);

    const mime = (msg.fileType && msg.fileType.startsWith('image/')) ? msg.fileType : 'image/jpeg';
    const dataUri = `data:${mime};base64,${decryptedB64}`;
    decryptedImageCache.set(msg.id, dataUri);

    FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => {});
    return dataUri;
  } catch (e) {
    console.error('[Image] Decrypt failed for', msg.id, e.message, e.stack);
    return null;
  }
}

// ===================== Превью изображения =====================
function MessageImage({ msg, onPress }) {
  const [uri, setUri] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    decryptAndCacheImage(msg).then((u) => {
      if (!alive) return;
      if (u) setUri(u);
      else setFailed(true);
    });
    return () => { alive = false; };
  }, [msg.fileUrl, msg.fileKey, msg.fileIv, msg.fileType]); // ← добавили зависимости

  if (failed) {
    return (
      <View style={styles.fileAttachment}>
        <Ionicons name="alert-circle-outline" size={18} color="#aaa" />
        <Text style={styles.fileName}>Failed to load image</Text>
      </View>
    );
  }
  if (!uri) {
    return (
      <View style={styles.imagePlaceholder}>
        <ActivityIndicator size="small" color={colors.accent} />
      </View>
    );
  }
  return (
    <TouchableOpacity onPress={() => onPress(uri)} activeOpacity={0.9}>
      <Image source={{ uri }} style={styles.messageImage} resizeMode="cover" />
    </TouchableOpacity>
  );
}

export default function ChatDetailScreen({ route, navigation }) {
  const { address, name, isGroup } = route.params;
  const {
    messages,
    setMessages,
    addMessage,
    updateMessage,
    removeMessage,
    setCurrentChat,
    updateConversationPreview
  } = useChatStore();
  const { address: myAddress } = useUserStore();
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [attachment, setAttachment] = useState(null);
  const flatListRef = useRef(null);
  const [hasMore, setHasMore] = useState(true);
  const [keyboardHeight, setKeyboardHeight] = useState(0);
  const [lightboxUri, setLightboxUri] = useState(null);
  const [lightboxVisible, setLightboxVisible] = useState(false);

  // Скрываем таб-бар
  useFocusEffect(
    useCallback(() => {
      const parent = navigation.getParent();
      if (parent) {
        parent.setOptions({ tabBarStyle: { display: 'none' } });
      }
      return () => {
        if (parent) {
          parent.setOptions({
            tabBarStyle: {
              position: 'absolute',
              bottom: 16,
              left: 16,
              right: 16,
              height: 70,
              borderRadius: 60,
              backgroundColor: 'transparent',
              borderTopWidth: 0,
              elevation: 0,
            },
          });
        }
      };
    }, [navigation])
  );

  // Клавиатура
  useEffect(() => {
    const showSub = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow',
      (e) => setKeyboardHeight(e.endCoordinates.height)
    );
    const hideSub = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide',
      () => setKeyboardHeight(0)
    );
    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  // Устанавливаем текущий чат в store при входе и сбрасываем при выходе
   // Устанавливаем текущий чат в store при входе и сбрасываем при выходе
  useEffect(() => {
    setCurrentChat({ address, name, isGroup });
    loadMessages();
    return () => {
      setCurrentChat(null);

    };
  }, [address]);

  const openLightbox = (uri) => {
    setLightboxUri(uri);
    setLightboxVisible(true);
  };

  const shareLightboxImage = async () => {
    if (!lightboxUri) return;
    try {
      await Share.share({ url: lightboxUri });
    } catch (e) {
      Alert.alert('Error', 'Could not share image');
    }
  };

  const handleAddToContacts = async () => {
    if (isGroup) return;
    try {
      const contactName = name && name !== address.slice(0, 10) + '…'
        ? name
        : 'Contact_' + address.slice(0, 8);
      await addContact(contactName, address);
      Alert.alert('Success', 'Contact added');
    } catch (e) {
      Alert.alert('Error', e.message || 'Failed to add contact');
    }
  };

  const handleClearConversation = () => {
    Alert.alert('Clear conversation', 'Delete all messages in this chat?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Clear',
        style: 'destructive',
        onPress: async () => {
          try {
            const res = await fetch(`${API_BASE_URL}/clear_conversation`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ chat_with: address }),
            });
            if (!res.ok) throw new Error('Failed');
            setMessages([]);
            clearMessageCache(address);
            updateConversationPreview(address, '');
          } catch (e) {
            Alert.alert('Error', e.message);
          }
        },
      },
    ]);
  };

  const handleCall = (video) => {
    Alert.alert(
      video ? 'Video call' : 'Voice call',
      'Calling not yet implemented in mobile. Needs WebRTC layer.'
    );
  };

  useEffect(() => {
    navigation.setOptions({
      title: name || address.slice(0, 10),
      headerStyle: { backgroundColor: colors.bgPrimary, borderBottomWidth: 0 },
      headerTitleStyle: { color: colors.textMain },
      headerTintColor: colors.textMain,
      headerLeft: () => (
        <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginLeft: 10 }}>
          <Ionicons name="arrow-back" size={24} color={colors.textMain} />
        </TouchableOpacity>
      ),
      headerRight: () => (
        <View style={styles.headerActions}>
          {!isGroup && (
            <TouchableOpacity onPress={() => handleCall(false)} style={styles.headerBtn}>
              <Ionicons name="call-outline" size={22} color={colors.textMain} />
            </TouchableOpacity>
          )}
          {!isGroup && (
            <TouchableOpacity onPress={() => handleCall(true)} style={styles.headerBtn}>
              <Ionicons name="videocam-outline" size={22} color={colors.textMain} />
            </TouchableOpacity>
          )}
          {!isGroup && (
            <TouchableOpacity onPress={handleAddToContacts} style={styles.headerBtn}>
              <Ionicons name="person-add-outline" size={20} color={colors.textMain} />
            </TouchableOpacity>
          )}
          <TouchableOpacity onPress={handleClearConversation} style={styles.headerBtn}>
            <Ionicons name="trash-outline" size={20} color={colors.danger} />
          </TouchableOpacity>
        </View>
      ),
    });
  }, [navigation, name, address, isGroup]);

   const loadMessages = async (loadMore = false) => {
  if (loading) return;

  // ✅ Если не loadMore и есть кеш — показываем кеш мгновенно
  if (!loadMore) {
    const cached = getCachedMessages(address);
    if (cached.length > 0) {
      setMessages(cached);
      // Фоновая проверка на новые сообщения (silent)
      refreshMessages();
      return;
    }
  }

  setLoading(true);
  try {
    const currentMessages = useChatStore.getState().messages;
    const beforeId = loadMore && currentMessages.length > 0 ? currentMessages[0].id : null;
    const data = await getConversation(address, beforeId);
    const rawMessages = data.messages || [];

    const decryptedMessages = await Promise.all(
      rawMessages.map(async (msg) => {
        try {
          return await processMessageDecryption(msg);
        } catch (e) {
          return { ...msg, content: '🔒 Decrypt error', isDecrypted: false };
        }
      })
    );

    if (loadMore) {
      if (decryptedMessages.length === 0) {
        setHasMore(false);
      } else {
        setMessages((prev) => {
          const existingIds = new Set(prev.map(m => m.id));
          const newOnes = decryptedMessages.filter(m => !existingIds.has(m.id));
          return [...newOnes, ...prev];
        });
      }
    } else {
      setMessages(decryptedMessages);
      setHasMore(decryptedMessages.length >= 20);
      decryptedMessages.forEach(msg => addMessageToCache(address, msg));
    }
  } catch (e) {
    Alert.alert('Error', 'Failed to load messages');
  } finally {
    setLoading(false);
  }
};

   // Фоновое обновление (без лоадера)
   const refreshMessages = async () => {
  try {
    const data = await getConversation(address);
    const rawMessages = data.messages || [];

    const decryptedMessages = await Promise.all(
      rawMessages.map(async (msg) => {
        try {
          return await processMessageDecryption(msg);
        } catch (e) {
          return { ...msg, content: '🔒 Decrypt error', isDecrypted: false };
        }
      })
    );

    // Обновляем только если есть новые сообщения
    const currentIds = new Set(useChatStore.getState().messages.map(m => m.id));
    const hasNew = decryptedMessages.some(m => !currentIds.has(m.id));

    if (hasNew) {
      setMessages(decryptedMessages);
      decryptedMessages.forEach(msg => addMessageToCache(address, msg));
    }
  } catch (e) {
    // silent fail
  }
};

  // Прокрутка вниз при новых сообщениях
  useEffect(() => {
    if (messages.length > 0) {
      setTimeout(() => {
        flatListRef.current?.scrollToEnd({ animated: true });
      }, 100);
    }
  }, [messages.length]);

  const handleSend = async () => {
  const content = input.trim();
  if (!content && !attachment) {
    Alert.alert('Error', 'Enter a message or attach a file');
    return;
  }
  if (sending) return;

  setSending(true);
  const tempId = `temp_${Date.now()}`;
  const tempMsg = {
    id: tempId,
    sender: myAddress,
    content: content || '',
    timestamp: Date.now() / 1000,
    is_mine: true,
    status: 'sending',
  };
  if (attachment) {
    // Показываем временный файл с оригинальным типом и URI (позже обновим)
    tempMsg.fileType = attachment.type;
    tempMsg.fileUrl = attachment.uri;
  }
  addMessage(tempMsg);
  setInput('');
  setAttachment(null);

  try {
    // ===== СЖАТИЕ ФАЙЛА (если есть) =====
    let fileToUpload = null;
    if (attachment) {
      // Подготавливаем файл: сжимаем изображения и видео
      fileToUpload = await prepareFileForUpload(attachment);
      // fileToUpload содержит новые uri, type, name
    }

    // Загружаем зашифрованный файл на сервер
    let fileAttachment = null;
    if (fileToUpload) {
      fileAttachment = await uploadEncryptedFile(fileToUpload);
      // fileAttachment теперь содержит url, key, iv, type (если добавили type в uploadEncryptedFile)
    }

    // Отправляем сообщение (текст + ссылка на файл)
    const result = await sendEncryptedMessage(
      address,
      content,
      fileAttachment,
      isGroup,
      isGroup ? address.replace('group:', '') : null
    );

    // Обновляем временное сообщение серверными данными
    updateMessage(tempId, {
      id: result.tx_id || tempId,
      status: 'sent',
      fileUrl: fileAttachment?.url || fileToUpload?.uri || attachment?.uri,
      fileKey: fileAttachment?.key,
      fileIv: fileAttachment?.iv,
      fileType: fileAttachment?.type || fileToUpload?.type || attachment?.type,
    });

    updateConversationPreview(address, content.slice(0, 40) || '📎 File');
  } catch (e) {
    console.error('Send error:', e);
    removeMessage(tempId);
    Alert.alert('Error', e.message || 'Failed to send');
  } finally {
    setSending(false);
  }
};

  // 🆕 ВСТАВЬТЕ СЮДА
  const handleDeleteMessage = (msg) => {
  // 1. Проверка: нельзя удалять отправляемые
  if (msg.status === 'sending') {
    Alert.alert('Error', 'Cannot delete message while sending');
    return;
  }

  // 2. Проверка: можно удалять только свои сообщения
  if (!msg.is_mine) {
    Alert.alert('Failed', 'You can only delete your own messages');
    return;
  }

  Alert.alert(
    'Delete Message',
    'Are you sure you want to delete this message?',
    [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            // ✅ Правильный вызов (POST /delete_message с телом)
            const res = await fetch(`${API_BASE_URL}/delete_message`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ message_id: msg.id }),
            });

            if (!res.ok) {
              const errorData = await res.json().catch(() => ({}));
              throw new Error(errorData.error || 'Failed to delete');
            }

            // Удаляем из локального состояния
            setMessages(prev => prev.filter(m => m.id !== msg.id));

            // Очищаем кеш и перезагружаем (чтобы синхронизировать)
            clearMessageCache(address);
            await loadMessages(); // перезагрузит сообщения с сервера
          } catch (e) {
            Alert.alert('Error', e.message || 'Failed to delete message');
          }
        },
      },
    ]
  );
};

  const pickImage = async () => {
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        quality: 0.7,
      });
      if (!result.canceled && result.assets?.length > 0) {
        const asset = result.assets[0];
        setAttachment({
          uri: asset.uri,
          type: asset.mimeType || 'image/jpeg',
          name: asset.fileName || 'image.jpg',
        });
      }
    } catch (e) {
      Alert.alert('Error', 'Failed to pick image');
    }
  };

  const pickFile = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: '*/*',
        copyToCacheDirectory: true,
      });
      if (!result.canceled && result.assets?.length > 0) {
        const file = result.assets[0];
        setAttachment({
          uri: file.uri,
          type: file.mimeType || 'application/octet-stream',
          name: file.name || 'file',
        });
      }
    } catch (e) {
      Alert.alert('Error', 'Failed to pick file');
    }
  };

  const renderItem = ({ item, index }) => {
  const isMine = item.is_mine;
  const showSender = isGroup && !isMine && item.sender;
  const senderName = showSender ? (item.sender_name || item.sender.slice(0, 10)) : null;
  const isImage = item.fileType && item.fileType.startsWith('image/');
  const isAudio = item.fileType && item.fileType.startsWith('audio/');

  const showDateDivider = index === 0 ||
    new Date(messages[index - 1]?.timestamp * 1000).toDateString() !==
    new Date(item.timestamp * 1000).toDateString();

  let statusIcon = null;
  if (isMine) {
    if (item.status === 'sending') {
      statusIcon = <ActivityIndicator size="small" color="rgba(255,255,255,0.5)" style={{ marginLeft: 4 }} />;
    } else if (item.status === 'sent') {
      statusIcon = <Text style={styles.statusIcon}>✓</Text>;
    } else if (item.status === 'delivered') {
      statusIcon = <Text style={styles.statusIcon}>✓✓</Text>;
    } else if (item.status === 'read') {
      statusIcon = <Text style={[styles.statusIcon, styles.statusRead]}>✓✓</Text>;
    }
  }

  const timeStr = item.timestamp
    ? new Date(item.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  return (
    <>
      {showDateDivider && (
        <View style={styles.dateDivider}>
          <Text style={styles.dateText}>
            {new Date(item.timestamp * 1000).toLocaleDateString(undefined, {
              day: 'numeric',
              month: 'long',
              year: new Date(item.timestamp * 1000).getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined,
            })}
          </Text>
        </View>
      )}

      {/* Оборачиваем сообщение в TouchableOpacity для long press */}
      <TouchableOpacity
        activeOpacity={0.7}
        onLongPress={() => handleDeleteMessage(item)}   // ← добавляем
        style={[
          styles.messageRow,
          isMine ? styles.myMessage : styles.otherMessage,
          item.status === 'sending' && styles.sendingMessage,
        ]}
      >
        {showSender && (
          <Text style={styles.senderName}>{senderName}</Text>
        )}

        {item.fileUrl && isImage && (
          <MessageImage msg={item} onPress={openLightbox} />
        )}

        {item.fileUrl && isAudio && (
          <View style={styles.audioAttachment}>
            <Ionicons name="musical-note" size={20} color={colors.accent} />
            <Text style={styles.audioText}>Voice message</Text>
          </View>
        )}

        {item.fileUrl && !isImage && !isAudio && (
          <TouchableOpacity
            style={styles.fileAttachment}
            onPress={() => Alert.alert('File', item.fileUrl.split('/').pop())}
          >
            <Ionicons name="document-outline" size={20} color="#aaa" />
            <Text style={styles.fileName} numberOfLines={1}>
              {item.fileUrl.split('/').pop() || 'File'}
            </Text>
            <Ionicons name="download-outline" size={16} color={colors.accent} />
          </TouchableOpacity>
        )}

        {!!item.content && (
          <Text style={[
            styles.messageText,
            item.content.startsWith('🔒') && styles.errorText,
          ]}>
            {item.content}
          </Text>
        )}

        <View style={styles.metaRow}>
          <Text style={styles.time}>{timeStr}</Text>
          {statusIcon}
        </View>
      </TouchableOpacity>
    </>
  );
};

  const bottomOffset = keyboardHeight > 0
    ? (Platform.OS === 'ios' ? keyboardHeight : 0)
    : 0;

  return (
    <SafeAreaView style={styles.container}>
      {loading && messages.length === 0 ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={styles.loading}>Loading messages...</Text>
        </View>
      ) : (
        <FlatList
          ref={flatListRef}
          data={messages}
          keyExtractor={(item) => item.id.toString()}
          renderItem={renderItem}
          contentContainerStyle={{
            paddingVertical: 16,
            paddingHorizontal: 12,
            paddingBottom: bottomOffset + 80,
          }}
          onEndReached={() => { if (!loading && hasMore && messages.length) loadMessages(true); }}
          onEndReachedThreshold={0.3}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Ionicons name="chatbubble-ellipses-outline" size={64} color="#444" />
              <Text style={styles.emptyText}>No messages yet</Text>
              <Text style={styles.emptySub}>Say hello!</Text>
            </View>
          }
        />
      )}

      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
        style={[styles.inputWrapper, { bottom: bottomOffset }]}
      >
        <BlurView intensity={20} tint="dark" style={styles.inputContainer}>
          <TouchableOpacity onPress={pickImage} style={styles.attachButton}>
            <Ionicons name="image-outline" size={24} color={colors.textMuted} />
          </TouchableOpacity>
          <TouchableOpacity onPress={pickFile} style={styles.attachButton}>
            <Ionicons name="attach-outline" size={24} color={colors.textMuted} />
          </TouchableOpacity>

          {attachment && (
            <View style={styles.attachmentPreview}>
              <Text style={styles.attachmentName} numberOfLines={1}>{attachment.name}</Text>
              <TouchableOpacity onPress={() => setAttachment(null)}>
                <Ionicons name="close-circle" size={18} color={colors.danger} />
              </TouchableOpacity>
            </View>
          )}

          <TextInput
            style={styles.input}
            value={input}
            onChangeText={setInput}
            placeholder="Type a message..."
            placeholderTextColor={colors.textMuted}
            multiline
            maxHeight={100}
            onFocus={() => {
              setTimeout(() => flatListRef.current?.scrollToEnd({ animated: true }), 300);
            }}
          />

          <TouchableOpacity
            style={[
              styles.sendButton,
              (sending || (!input.trim() && !attachment)) && styles.sendDisabled
            ]}
            onPress={handleSend}
            disabled={sending || (!input.trim() && !attachment)}
          >
            {sending ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Ionicons name="send" size={20} color="#fff" />
            )}
          </TouchableOpacity>
        </BlurView>
      </KeyboardAvoidingView>

      <Modal
        visible={lightboxVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setLightboxVisible(false)}
      >
        <View style={styles.lightboxOverlay}>
          <TouchableOpacity
            style={styles.lightboxClose}
            onPress={() => setLightboxVisible(false)}
          >
            <Ionicons name="close" size={30} color="#fff" />
          </TouchableOpacity>
          {lightboxUri && (
            <Image
              source={{ uri: lightboxUri }}
              style={styles.lightboxImage}
              resizeMode="contain"
            />
          )}
          <TouchableOpacity style={styles.lightboxShareBtn} onPress={shareLightboxImage}>
            <Ionicons name="share-outline" size={18} color="#fff" />
            <Text style={styles.lightboxShareText}>Share</Text>
          </TouchableOpacity>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loading: {
    color: colors.textMain,
    marginTop: 10,
  },
  headerActions: {
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 8,
  },
  headerBtn: {
    padding: 6,
    marginLeft: 4,
  },
  dateDivider: {
    alignItems: 'center',
    marginVertical: 12,
  },
  dateText: {
    color: colors.textMuted,
    fontSize: 12,
    backgroundColor: 'rgba(255,255,255,0.05)',
    paddingHorizontal: 14,
    paddingVertical: 5,
    borderRadius: 12,
    fontWeight: '500',
    letterSpacing: 0.3,
    overflow: 'hidden',
  },
  messageRow: {
    marginVertical: 3,
    maxWidth: '78%',
    padding: 12,
    borderRadius: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
    elevation: 2,
  },
  myMessage: {
    alignSelf: 'flex-end',
    backgroundColor: colors.accent,
    borderBottomRightRadius: 4,
    marginLeft: '22%',
  },
  otherMessage: {
    alignSelf: 'flex-start',
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    borderBottomLeftRadius: 4,
    marginRight: '22%',
  },
  sendingMessage: {
    opacity: 0.7,
  },
  senderName: {
    color: colors.accent,
    fontSize: 12,
    marginBottom: 5,
    fontWeight: '700',
    letterSpacing: 0.2,
  },
  messageText: {
    color: colors.textMain,
    fontSize: 15,
    lineHeight: 21,
    letterSpacing: 0.1,
  },
  errorText: {
    color: '#ff6b6b',
    fontStyle: 'italic',
  },
  metaRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    alignItems: 'center',
    marginTop: 5,
    gap: 5,
  },
  time: {
    color: 'rgba(255,255,255,0.45)',
    fontSize: 10,
    fontWeight: '400',
  },
  statusIcon: {
    color: 'rgba(255,255,255,0.45)',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: -1,
    marginLeft: 2,
  },
  statusRead: {
    color: '#74b9ff',
  },
  fileAttachment: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.1)',
    padding: 10,
    borderRadius: 12,
    marginBottom: 6,
    gap: 8,
  },
  fileName: {
    color: colors.textMain,
    fontSize: 13,
    flex: 1,
  },
  audioAttachment: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.1)',
    padding: 10,
    borderRadius: 12,
    marginBottom: 6,
    gap: 8,
  },
  audioText: {
    color: colors.textMain,
    fontSize: 13,
  },
  messageImage: {
    width: 220,
    height: 220,
    borderRadius: 14,
    marginBottom: 6,
  },
  imagePlaceholder: {
    width: 220,
    height: 140,
    borderRadius: 14,
    marginBottom: 6,
    backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  inputWrapper: {
    position: 'absolute',
    left: 0,
    right: 0,
    paddingHorizontal: 10,
    paddingBottom: 10,
  },
  inputContainer: {
    flexDirection: 'row',
    padding: 8,
    alignItems: 'center',
    backgroundColor: 'rgba(30,30,45,0.95)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
    borderRadius: 28,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: -3 },
    shadowOpacity: 0.3,
    shadowRadius: 6,
    elevation: 8,
  },
  attachButton: {
    padding: 8,
  },
  attachmentPreview: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.1)',
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginRight: 6,
    maxWidth: 120,
  },
  attachmentName: {
    color: colors.textMain,
    fontSize: 12,
    flexShrink: 1,
    marginRight: 4,
  },
  input: {
    flex: 1,
    backgroundColor: 'transparent',
    paddingHorizontal: 10,
    paddingVertical: 8,
    color: colors.textMain,
    maxHeight: 100,
    minHeight: 40,
    fontSize: 15,
  },
  sendButton: {
    marginLeft: 6,
    backgroundColor: colors.accent,
    borderRadius: 22,
    padding: 10,
    minWidth: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendDisabled: {
    opacity: 0.4,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 100,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: 18,
    marginTop: 16,
  },
  emptySub: {
    color: '#555',
    fontSize: 14,
    marginTop: 8,
  },
  lightboxOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.94)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  lightboxClose: {
    position: 'absolute',
    top: 50,
    right: 20,
    zIndex: 1,
    padding: 10,
  },
  lightboxImage: {
    width: '100%',
    height: '80%',
  },
  lightboxShareBtn: {
    position: 'absolute',
    bottom: 50,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.accent,
    paddingHorizontal: 24,
    paddingVertical: 14,
    borderRadius: 50,
  },
  lightboxShareText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 15,
  },
});