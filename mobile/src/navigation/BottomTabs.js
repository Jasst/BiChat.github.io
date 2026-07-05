// src/navigation/BottomTabs.js
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createStackNavigator } from '@react-navigation/stack';
import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { colors } from '../theme';
import ChatScreen from '../screens/ChatScreen';
import ChatDetailScreen from '../screens/ChatDetailScreen';
import ContactsScreen from '../screens/ContactsScreen';
import GroupsScreen from '../screens/GroupsScreen';
import WalletScreen from '../screens/WalletScreen';
import ProfileScreen from '../screens/ProfileScreen';
// import AIChatScreen from '../screens/AIChatScreen'; // пока не реализован

const Tab = createBottomTabNavigator();
const Stack = createStackNavigator();

function ChatsStack() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        cardStyle: { backgroundColor: colors.bgPrimary },
      }}
    >
      <Stack.Screen name="ChatList" component={ChatScreen} />
      <Stack.Screen name="ChatDetail" component={ChatDetailScreen} />
      {/* <Stack.Screen name="AIChat" component={AIChatScreen} /> */}
    </Stack.Navigator>
  );
}

export default function BottomTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
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
        tabBarBackground: () => (
          <BlurView
            intensity={20}
            tint="dark"
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              borderRadius: 60,
              overflow: 'hidden',
              borderWidth: 1,
              borderColor: colors.glassBorder,
            }}
          />
        ),
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarLabelStyle: { fontSize: 10, fontWeight: '500', marginBottom: 4 },
        tabBarIconStyle: { marginTop: 4 },
        tabBarIcon: ({ focused, color, size }) => {
          let iconName;
          if (route.name === 'Chats') {
            iconName = focused ? 'chatbubbles' : 'chatbubbles-outline';
          } else if (route.name === 'Contacts') {
            iconName = focused ? 'people' : 'people-outline';
          } else if (route.name === 'Groups') {
            iconName = focused ? 'people-circle' : 'people-circle-outline';
          } else if (route.name === 'Wallet') {
            iconName = focused ? 'wallet' : 'wallet-outline';
          } else if (route.name === 'Profile') {
            iconName = focused ? 'person' : 'person-outline';
          }
          return <Ionicons name={iconName} size={24} color={color} />;
        },
      })}
    >
      <Tab.Screen name="Chats" component={ChatsStack} />
      <Tab.Screen name="Contacts" component={ContactsScreen} />
      <Tab.Screen name="Groups" component={GroupsScreen} />
      <Tab.Screen name="Wallet" component={WalletScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
    </Tab.Navigator>
  );
}