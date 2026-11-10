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
  const { brand, onBrand, crest } = palettes.light

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: brand,
          color: onBrand,
          fontFamily: 'Cinzel',
          fontSize: size * 0.56,
          fontWeight: 700,
          position: 'relative',
        }}
      >
        <span style={{ marginTop: size * 0.02, marginRight: size * 0.06 }}>P</span>
        <div
          style={{
            position: 'absolute',
            right: size * 0.22,
            bottom: size * 0.3,
            width: size * 0.1,
            height: size * 0.1,
            borderRadius: size,
            background: crest,
          }}
        />
      </div>
    ),
    {
      width: size,
      height: size,
      fonts: [{ name: 'Cinzel', data: await cinzel, weight: 700, style: 'normal' }],
    },
  )
}
