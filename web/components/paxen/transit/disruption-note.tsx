import type { Disruption } from '@/lib/types'
import { stillOnChance, stillOnWords } from '@/lib/plain'
import { Text } from '../primitives/text'

/** One disruption in plain words, with a gentle "will it still be on?" line when the API provides one. */
export function DisruptionNote({ disruption: d, withReason = true }: { disruption: Disruption; withReason?: boolean }) {
  const outlook = stillOnWords(stillOnChance(d))
  return (
    <div className="flex flex-col gap-0.5">
      <Text variant="footnote" tone="attention" className="text-pretty">
        <span style={{ fontWeight: 600 }}>{d.line_name}:</span> {d.description}
        {withReason && d.reason ? ` \u2014 ${d.reason}` : ''}
      </Text>
      {outlook && (
        <Text variant="footnote" tone="secondary" className="text-pretty">
          {outlook}
        </Text>
      )}
    </div>
  )
}
