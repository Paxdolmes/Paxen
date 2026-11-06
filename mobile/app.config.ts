/// <reference types="node" />
import type { ConfigContext, ExpoConfig } from 'expo/config'

// Paxen's iPhone app (React Native / Expo). Same bundle id as the earlier web-wrapped app, so TestFlight testers
// simply get the new version. Native folders are generated at build time (`expo prebuild`); never edit them.
export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'Paxen',
  slug: 'paxen',
  scheme: 'paxen',
  version: '1.0.0',
  orientation: 'portrait',
  userInterfaceStyle: 'automatic',
  icon: './assets/icon.png',
  ios: {
    bundleIdentifier: 'com.paxdolmes.paxen',
    // CI passes its run number, so every TestFlight upload gets a new build number.
    buildNumber: process.env.IOS_BUILD_NUMBER || '1',
    supportsTablet: false,
    infoPlist: {
      ITSAppUsesNonExemptEncryption: false,
      NSLocationWhenInUseUsageDescription:
        'Paxen uses your location only while a live trip is open, to show your progress. It is never stored.',
      UIBackgroundModes: ['remote-notification'],
    },
  },
  android: { package: 'com.paxdolmes.paxen' },
  web: { bundler: 'metro', output: 'single' },
  plugins: [
    'expo-router',
    ['expo-splash-screen', { image: './assets/icon.png', imageWidth: 120, backgroundColor: '#F2F1EE', dark: { image: './assets/icon.png', backgroundColor: '#111315' } }],
    ['expo-notifications', { mode: 'production' }],
    [
      'expo-location',
      { locationWhenInUsePermission: 'Paxen uses your location only while a live trip is open, to show your progress. It is never stored.' },
    ],
    '@react-native-community/datetimepicker',
  ],
  experiments: { typedRoutes: false },
  extra: {
    apiUrl: process.env.EXPO_PUBLIC_PAXEN_API_URL || 'https://paxen-production.up.railway.app',
  },
})
