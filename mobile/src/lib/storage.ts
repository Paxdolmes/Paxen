import AsyncStorage from '@react-native-async-storage/async-storage'

/** A string value persisted on the phone, readable synchronously once loaded, with change subscribers. */
export function persisted(key: string) {
  let value: string | null | undefined // undefined until loaded from storage
  const listeners = new Set<() => void>()
  const emit = () => listeners.forEach((l) => l())

  const ready = AsyncStorage.getItem(key)
    .catch(() => null)
    .then((v) => {
      if (value === undefined) value = v
      emit()
    })

  return {
    ready,
    /** undefined while still loading, null when unset. */
    get: () => value,
    set(v: string | null) {
      value = v
      emit()
      ;(v == null ? AsyncStorage.removeItem(key) : AsyncStorage.setItem(key, v)).catch(() => {})
    },
    subscribe(cb: () => void) {
      listeners.add(cb)
      return () => {
        listeners.delete(cb)
      }
    },
  }
}
