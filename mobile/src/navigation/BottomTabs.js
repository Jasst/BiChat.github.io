import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createStackNavigator } from '@react-navigation/stack';
import { Ionicons } from '@expo/vector-icons';
import ChatScreen from '../screens/ChatScreen';
import ChatDetailScreen from '../screens/ChatDetailScreen';
import ContactsScreen from '../screens/ContactsScreen';
import GroupsScreen from '../screens/GroupsScreen';
import WalletScreen from '../screens/WalletScreen';
import ProfileScreen from '../screens/ProfileScreen';

const Tab = createBottomTabNavigator();
const Stack = createStackNavigator();

function ChatsStack() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      <Stack.Screen name="ChatList" component={ChatScreen} />
      <Stack.Screen name="ChatDetail" component={ChatDetailScreen} />
    </Stack.Navigator>
  );
}

export default function BottomTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: {
          backgroundColor: '#141414',
          borderTopColor: '#2a2a2a',
          paddingBottom: 6,
          height: 70,
        },
        tabBarActiveTintColor: '#6c5ce7',
        tabBarInactiveTintColor: '#a4b0be',
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: '500',
        },
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