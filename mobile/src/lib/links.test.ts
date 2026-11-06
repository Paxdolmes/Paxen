import assert from 'node:assert/strict'
import { test } from 'node:test'
import { routeFor } from './links.ts'

test('alert links open the right screen', () => {
  assert.equal(routeFor('/?tab=alerts'), '/alerts')
  assert.equal(routeFor('/?tab=today&live=1'), '/live')
  assert.equal(routeFor('/'), '/')
  assert.equal(routeFor('/?tab=nonsense'), '/')
  assert.equal(routeFor(undefined), null)
})
