import clsx from 'clsx'
import type { PropsWithChildren, ReactNode } from 'react'

interface BentoCardProps extends PropsWithChildren {
  title?: ReactNode
  right?: ReactNode
  className?: string
}

export function BentoCard({ title, right, className, children }: BentoCardProps) {
  return (
    <article
      className={clsx(
        'gmz-panel relative overflow-hidden p-4 before:absolute before:left-0 before:right-0 before:top-0 before:h-1 before:bg-[linear-gradient(90deg,#9ac0ff,#dbe9ff_60%,#ffffff)]',
        className,
      )}
    >
      {(title || right) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title ? <h2 className="text-lg font-semibold text-slate-900">{title}</h2> : <span />}
          {right}
        </header>
      )}
      {children}
    </article>
  )
}
