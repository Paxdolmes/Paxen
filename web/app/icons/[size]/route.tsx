import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { ImageResponse } from 'next/og'
import { palettes } from '@/lib/paxen-tokens'

const ALLOWED = new Set([180, 192, 512, 1024])

// Pre-rendered at build time (also lets the iPhone app's static build include them)
export const dynamic = 'force-static'
export function generateStaticParams() {
  return [...ALLOWED].map((size) => ({ size: String(size) }))
}

// Cinzel 700, subset to the single glyph "P" (SIL Open Font License), vendored so the build needs no network.
const cinzel = readFile(join(process.cwd(), 'assets/cinzel-700-p.ttf'))

export async function GET(_req: Request, { params }: { params: Promise<{ size: string }> }) {
  const { size: raw } = await params
  const size = ALLOWED.has(Number(raw)) ? Number(raw) : 192
  const { border: silver, accent: crimson, text: ink, surface: outline } = palettes.light
  // A white keyline (as on the crest) lets the ink "P" read on both the silver field and the crimson pale: a
  // white-stroked "P" underneath, the ink "P" on top. (One centred stroke; offset text-shadows render lopsided.)
  const k = Math.max(1, Math.round(size * 0.012))
  const letter = {
    position: 'absolute' as const,
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: 'Cinzel',
    fontWeight: 700,
    fontSize: size * 0.62,
    lineHeight: 1,
    paddingTop: size * 0.04,
    paddingLeft: size * 0.03,
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: silver,
          position: 'relative',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: (size - size * 0.22) / 2,
            width: size * 0.22,
            background: crimson,
          }}
        />
        <div style={{ ...letter, color: outline, WebkitTextStroke: `${k * 2}px ${outline}` }}>P</div>
        <div style={{ ...letter, color: ink }}>P</div>
      </div>
    ),
    {
      width: size,
      height: size,
      fonts: [{ name: 'Cinzel', data: await cinzel, weight: 700, style: 'normal' }],
    },
  )
}
