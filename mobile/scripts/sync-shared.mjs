// The app shares its API contract and wording with the web app: these files are copied from web/lib so both stay
// identical. `npm run sync-shared` copies them; `npm run check-shared` (CI) fails if they've drifted.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const FILES = ['types.ts', 'format.ts', 'plain.ts', 'paxen-tokens.ts']
const HEADER = '// Copied from web/lib by scripts/sync-shared.mjs. Edit the web copy, then run `npm run sync-shared`.\n'
const check = process.argv.includes('--check')
let drift = 0
for (const f of FILES) {
  const src = HEADER + readFileSync(join(here, '../../web/lib', f), 'utf8')
  const dest = join(here, '../src/shared', f)
  if (check) {
    let cur = ''
    try { cur = readFileSync(dest, 'utf8') } catch {}
    if (cur !== src) { console.error(`src/shared/${f} differs from web/lib/${f}: run npm run sync-shared`); drift++ }
  } else writeFileSync(dest, src)
}
process.exit(drift ? 1 : 0)
