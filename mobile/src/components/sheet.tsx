import type { ReactNode } from 'react'
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { X } from 'lucide-react-native'
import { radii } from '@/shared/paxen-tokens'
import { usePalette, useShadow } from '@/lib/theme'
import { Text } from './text'
import { Button } from './ui'

/** Bottom sheet: slides up over a dimmed backdrop; tap outside, the close button or swipe-back closes it. */
export function Sheet({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  const p = usePalette()
  const shadow = useShadow('raised')
  const insets = useSafeAreaInsets()
  return (
    <Modal visible={open} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, justifyContent: 'flex-end' }}>
        <Pressable accessibilityLabel="Close" onPress={onClose} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: p.overlay }} />
        <View
          style={[
            { maxHeight: '88%', backgroundColor: p.surfaceRaised, borderTopLeftRadius: radii.xl, borderTopRightRadius: radii.xl, paddingTop: 12 },
            shadow,
          ]}
        >
          <View style={{ alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: p.borderStrong }} />
          <View style={{ flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, paddingHorizontal: 20, paddingTop: 12 }}>
            <Text variant="title2" accessibilityRole="header" style={{ flex: 1 }}>
              {title}
            </Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Close" onPress={onClose} hitSlop={8} style={{ width: 36, height: 36, alignItems: 'center', justifyContent: 'center' }}>
              <X size={20} color={p.textSecondary} />
            </Pressable>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 12, paddingHorizontal: 20, paddingTop: 12, paddingBottom: 12 }}>
            {children}
          </ScrollView>
          {footer && <View style={{ gap: 8, paddingHorizontal: 20, paddingTop: 8, paddingBottom: Math.max(20, insets.bottom + 8) }}>{footer}</View>}
          {!footer && <View style={{ height: Math.max(20, insets.bottom) }} />}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  )
}

export function ConfirmSheet({
  open,
  onClose,
  title,
  body,
  confirmLabel,
  onConfirm,
  loading,
}: {
  open: boolean
  onClose: () => void
  title: string
  body: string
  confirmLabel: string
  onConfirm: () => void
  loading?: boolean
}) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="danger" block onPress={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
          <Button variant="secondary" block onPress={onClose} disabled={loading}>
            Cancel
          </Button>
        </>
      }
    >
      <Text variant="body" tone="secondary">
        {body}
      </Text>
    </Sheet>
  )
}
