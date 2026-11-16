import assert from 'node:assert/strict'
import { test } from 'node:test'
import { activityProps, widgetEntries, WIDGET_FRESH_MS } from './surface-data.ts'

const at = (hhmm: string) => `2026-11-16T${hhmm}:00Z`
const t = (hhmm: string) => new Date(at(hhmm)).getTime()

test('the lock screen says what you are doing and when you arrive', () => {
  const live = {
    status: 'active', summary: 'District', eta: at('08:24'), phase: 'waiting' as const, current_leg: 1,
    legs: [{ line_name: null, from: 'Home', to: 'Fulham Broadway' }, { line_name: 'District', from: 'Fulham Broadway', to: 'Victoria' }],
    next_departure: { line_name: 'District', stop: 'Fulham Broadway', catch_index: 0, trains: [{ at: at('08:03') }] },
    disruptions: [{ line_name: 'District', description: 'Minor delays' }],
  }
  assert.deepEqual(activityProps(live), {
    status: 'active', summary: 'District', eta: t('08:24'), headline: 'Wait for the District at Fulham Broadway',
    next: 'District from Fulham Broadway', nextAt: t('08:03'), note: 'District: Minor delays',
  })
  const riding = activityProps({ ...live, phase: 'on_board' })
  assert.equal(riding.headline, 'On the District to Victoria')
  assert.equal(riding.next, null)
  assert.equal(activityProps({ ...live, status: 'arrived' }).headline, 'You\u2019ve arrived')
})

test('the widget shows when to leave, then falls back once the times have aged', () => {
  const ev = {
    commute: { id: 'c1', name: 'To work' }, status: 'slower', delta_min: 13.6, baseline: { p50: 32 },
    recommended: { summary: 'District', depart_at: at('08:00'), arrive_at: at('08:40'), leave_by: { at: at('08:05') } },
  }
  const [live, stale] = widgetEntries({ generated_at: at('08:00'), active_commute_id: 'c1', commutes: [ev] })
  assert.equal(live.props.statusLabel, '14 min slower')
  assert.equal(live.props.leaveAt, t('08:05'))
  assert.equal(live.props.arriveAt, t('08:40'))
  assert.equal(stale.at, t('08:00') + WIDGET_FRESH_MS)
  assert.equal(stale.props.stale, true)
  assert.equal(stale.props.usual, 'Usually 32 min')

  const now = widgetEntries({ generated_at: at('08:00'), active_commute_id: 'c1', commutes: [{ ...ev, status: 'on_time', delta_min: 0, recommended: { ...ev.recommended, leave_by: null } }] })
  assert.equal(now[0].props.leaveText, 'Now')
  assert.equal(now[0].props.statusLabel, 'All good')

  // tonight's commute home, seen at 08:00: its start time holds until then
  const evening = widgetEntries({ generated_at: at('08:00'), active_commute_id: 'c1', commutes: [{ ...ev, recommended: { ...ev.recommended, depart_at: at('17:30'), arrive_at: at('18:05'), leave_by: null } }] })
  assert.equal(evening[0].props.leaveAt, t('17:30'))
  assert.equal(evening[1].at, t('17:30'))
  assert.deepEqual(widgetEntries({ generated_at: at('08:00'), active_commute_id: null, commutes: [] }), [])
})
