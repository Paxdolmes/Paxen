import type { MetadataRoute } from 'next'
import { palettes } from '@/lib/paxen-tokens'

export const dynamic = 'force-static'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Paxen',
    short_name: 'Paxen',
    description: 'Know when your normal commute is not normal.',
    start_url: '/',
    display: 'standalone',
    orientation: 'portrait',
    background_color: palettes.light.canvas,
    theme_color: palettes.light.brand,
    icons: [
      { src: '/icons/192', sizes: '192x192', type: 'image/png' },
      { src: '/icons/512', sizes: '512x512', type: 'image/png' },
      { src: '/icons/512', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  }
}
