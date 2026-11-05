import { CircleAlert, CircleCheck, CircleHelp, TriangleAlert, Users } from 'lucide-react'
import type { CommuteStatus, LineCategory, RouteOption } from '@/lib/types'
import { Chip, type ChipTone } from '../primitives/chip'
import { Text } from '../primitives/text'

export const commuteStatusMeta: Record<
  CommuteStatus,
  { label: string; tone: ChipTone; headerClass: string; icon: typeof CircleCheck }
> = {
  normal: { label: 'All good', tone: 'success', headerClass: 'bg-px-success-soft text-px-on-success-soft', icon: CircleCheck },
  watch: { label: 'Keep an eye on it', tone: 'watch', headerClass: 'bg-px-watch-soft text-px-on-watch-soft', icon: TriangleAlert },
  slower: { label: 'Slower than usual', tone: 'attention', headerClass: 'bg-px-attention-soft text-px-on-attention-soft', icon: CircleAlert },
  disrupted: { label: 'Disrupted', tone: 'attentionStrong', headerClass: 'bg-px-attention text-px-on-attention', icon: CircleAlert },
  unknown: { label: 'Still learning', tone: 'neutral', headerClass: 'bg-px-surface-sunken text-px-text', icon: CircleHelp },
}

export function CommuteStatusPill({ status }: { status: CommuteStatus }) {
  const m = commuteStatusMeta[status]
  const Icon = m.icon
  return (
    <Chip tone={m.tone} icon={<Icon className="size-3.5" aria-hidden />}>
      {m.label}
    </Chip>
  )
}

export const lineCategoryTone: Record<LineCategory, 'success' | 'watch' | 'attention'> = {
  good: 'success',
  minor: 'watch',
  severe: 'attention',
  part_suspended: 'attention',
  suspended: 'attention',
}

const dotClass = { success: 'bg-px-success', watch: 'bg-px-watch', attention: 'bg-px-attention' }

export function SeverityDot({ category }: { category: LineCategory }) {
  return <span className={`size-2 shrink-0 rounded-full ${dotClass[lineCategoryTone[category]]}`} aria-hidden />
}

export function LineStatusText({ category, description }: { category: LineCategory; description: string }) {
  return (
    <Text variant="subhead" as="span" tone={lineCategoryTone[category]} style={{ fontWeight: 600 }}>
      {description}
    </Text>
  )
}

const crowdTone: Record<RouteOption['crowding']['level'], ChipTone> = {
  quiet: 'success',
  typical: 'neutral',
  busy: 'watch',
  busier: 'watch',
  very_busy: 'attention',
  'n/a': 'neutral',
}

export function CrowdingChip({ crowding }: { crowding: RouteOption['crowding'] }) {
  if (crowding.level === 'n/a') return null
  return (
    <Chip tone={crowdTone[crowding.level]} icon={<Users className="size-3.5" aria-hidden />}>
      <span className="sr-only">Estimated crowding: </span>
      {crowding.label}
    </Chip>
  )
}
