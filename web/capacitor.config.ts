import type { CapacitorConfig } from '@capacitor/cli'

// The iPhone app: the same web app (static build in web/out, MOBILE_BUILD=1) in a native shell, with native push.
const config: CapacitorConfig = {
  appId: 'com.paxdolmes.paxen',
  appName: 'Paxen',
  webDir: 'out',
  ios: {
    contentInset: 'never', // the web app already lays itself out around the notch and home bar (viewport-fit=cover)
    backgroundColor: '#ECEDEF', // = palettes.light.canvas (lib/paxen-tokens.ts)
  },
  plugins: {
    PushNotifications: { presentationOptions: ['banner', 'sound', 'badge'] },
  },
}

export default config
