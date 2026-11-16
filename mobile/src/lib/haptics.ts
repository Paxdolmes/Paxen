import { Platform } from 'react-native'
import * as Haptics from 'expo-haptics'

// A small physical confirmation for the few actions that matter. Never essential, so failures are ignored.
const on = Platform.OS === 'ios' || Platform.OS === 'android'

/** A light tap: something was picked or switched. */
export const tap = () => {
  if (on) Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {})
}

/** Done: a trip started, or you arrived. */
export const success = () => {
  if (on) Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {})
}
