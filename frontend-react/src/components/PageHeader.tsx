import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  subtitle?: string
  right?: ReactNode
}

export function PageHeader({ title, subtitle, right }: PageHeaderProps) {
  return (
    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-[clamp(1.5rem,2.4vw,2rem)] font-bold tracking-tight text-[#14151a]">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-[#5f6874]">{subtitle}</p> : null}
      </div>
      {right}
    </div>
  )
}
