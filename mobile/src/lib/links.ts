/** "/?tab=alerts" (what the server puts in each alert) -> an app route. Pure, so it can be tested in Node. */
export function routeFor(url: string | undefined): string | null {
  if (!url) return null
  const params = new URLSearchParams(url.split('?')[1] ?? '')
  const tab = params.get('tab')
  if (params.get('live') === '1') return '/live'
  return tab && ['routes', 'network', 'alerts', 'you'].includes(tab) ? `/${tab}` : '/'
}
