import { Suspense } from 'react'
import { PaxenApp } from '@/components/paxen/paxen-app'

export default function Page() {
  return (
    <Suspense fallback={null}>
      <PaxenApp />
    </Suspense>
  )
}
