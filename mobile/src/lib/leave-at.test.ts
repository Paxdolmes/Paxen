import assert from 'node:assert/strict'
import { test } from 'node:test'
import { departAtFor, nextQuarter } from './leave-at.ts'

const now = new Date(2026, 10, 16, 8, 7, 40)

test('now, in a while, or at a clock time', () => {
  assert.equal(departAtFor({ kind: 'now' }, now), null)
  assert.equal(departAtFor({ kind: 'in', min: 30 }, now), new Date(2026, 10, 16, 8, 37).toISOString())
  assert.equal(departAtFor({ kind: 'at', hhmm: '17:45' }, now), new Date(2026, 10, 16, 17, 45).toISOString())
  assert.equal(departAtFor({ kind: 'at', hhmm: '07:30' }, now), new Date(2026, 10, 17, 7, 30).toISOString()) // gone: tomorrow
})

test('the picker starts at the next quarter-hour', () => {
  assert.equal(nextQuarter(now), '08:30')
  assert.equal(nextQuarter(new Date(2026, 10, 16, 23, 50)), '00:15')
})
