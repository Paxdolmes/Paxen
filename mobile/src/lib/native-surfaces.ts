import type { ActivityProps, WidgetProps } from './surface-data'

// The lock-screen trip (Live Activity) and the home-screen widget exist on iPhone only: see native-surfaces.ios.ts.
// Everywhere else these do nothing.

export function syncTripActivity(_tripId: string, _props: ActivityProps): void {}

export async function endTripActivity(_final?: ActivityProps): Promise<void> {}

export function updateCommuteWidget(_entries: { at: number; props: WidgetProps }[]): void {}
