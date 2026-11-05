import { ImageResponse } from 'next/og'
import { palettes } from '@/lib/paxen-tokens'

const ALLOWED = new Set([180, 192, 512, 1024])

// Pre-rendered at build time (also lets the iPhone app's static build include them)
export const dynamic = 'force-static'
export function generateStaticParams() {
  return [...ALLOWED].map((size) => ({ size: String(size) }))
}

export async function GET(_req: Request, { params }: { params: Promise<{ size: string }> }) {
  const { size: raw } = await params
  const size = ALLOWED.has(Number(raw)) ? Number(raw) : 192
  const { brand, onBrand, attention } = palettes.light

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
          fontSize: size * 0.56,
          fontWeight: 700,
          letterSpacing: -size * 0.03,
          position: 'relative',
        }}
      >
        <span style={{ marginTop: -size * 0.06 }}>p</span>
        <div
          style={{
            position: 'absolute',
            right: size * 0.24,
            bottom: size * 0.26,
            width: size * 0.1,
            height: size * 0.1,
            borderRadius: size,
            background: attention,
          }}
        />
      </div>
    ),
    { width: size, height: size },
  )
}
