import { BentoCard } from '../components/BentoCard'
import { PageHeader } from '../components/PageHeader'

interface StubPageProps {
  title: string
  subtitle?: string
}

export function StubPage({ title, subtitle }: StubPageProps) {
  return (
    <section>
      <PageHeader title={title} subtitle={subtitle || 'Раздел в процессе переноса на React + TypeScript + Tailwind + Framer Motion'} />
      <BentoCard>
        <div className="text-sm text-slate-600">
          Этот раздел подключим следующим этапом. Контракт данных уже остается на `v1`, интерфейс будет приведен к единому Bento-стилю.
        </div>
      </BentoCard>
    </section>
  )
}
