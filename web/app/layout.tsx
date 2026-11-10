import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import { Cinzel, Inter } from 'next/font/google'
import { paxenCssVariables, palettes } from '@/lib/paxen-tokens'
import './globals.css'

const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' })
// Roman capitals for the wordmark only (echoing the "PAX" lettering on the crest behind the name).
const cinzel = Cinzel({ subsets: ['latin'], weight: ['700'], variable: '--font-cinzel', display: 'swap' })

export const metadata: Metadata = {
  title: 'Paxen — know when your normal commute is not normal',
  description:
    'Paxen learns your Home↔Work routine, watches London buses, Underground, Overground, Elizabeth line and National Rail, and tells you before you leave when a better route exists.',
  applicationName: 'Paxen',
  manifest: '/manifest.webmanifest',
  appleWebApp: { capable: true, title: 'Paxen', statusBarStyle: 'default' },
  icons: {
    icon: [{ url: '/icons/192', sizes: '192x192', type: 'image/png' }],
    apple: [{ url: '/icons/180', sizes: '180x180', type: 'image/png' }],
  },
  formatDetection: { telephone: false },
}

export const viewport: Viewport = {
  colorScheme: 'light dark',
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: palettes.light.canvas },
    { media: '(prefers-color-scheme: dark)', color: palettes.dark.canvas },
  ],
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en-GB" className={`${inter.variable} ${cinzel.variable} bg-px-canvas`}>
      <head>
        <style id="paxen-tokens" dangerouslySetInnerHTML={{ __html: paxenCssVariables() }} />
      </head>
      <body className="font-sans antialiased">
        {children}
        {process.env.NODE_ENV === 'production' && process.env.MOBILE_BUILD !== '1' && <Analytics />}
      </body>
    </html>
  )
}
