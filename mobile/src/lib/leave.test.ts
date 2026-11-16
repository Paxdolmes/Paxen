import assert from 'node:assert/strict'
import { test } from 'node:test'
import { leaveAdvice } from './leave.ts'

const at = (hhmm: string) => `2026-11-16T${hhmm}:00Z`
const now = new Date(at('08:00')).getTime()
const train = { at: at('08:05'), train_at: at('08:09'), line_name: 'District', stop: 'Fulham Broadway' }

test('minutes in hand count down to the latest time to leave', () => {
  assert.deepEqual(leaveAdvice(at('08:00'), train, now), { kind: 'wait', at: at('08:05'), inMin: 5, train })
  assert.equal(leaveAdvice(at('08:00'), train, now + 4.5 * 60_000).kind, 'now') // under a minute left: go
  assert.deepEqual(leaveAdvice(at('08:00'), train, now + 10 * 60_000), { kind: 'now', train: null }) // train gone
})

test('with nothing to gain, or before the commute starts, it is plain', () => {
  assert.deepEqual(leaveAdvice(at('08:00'), null, now), { kind: 'now', train: null })
  assert.deepEqual(leaveAdvice(at('17:30'), train, now), { kind: 'later', at: at('17:30') })
})
