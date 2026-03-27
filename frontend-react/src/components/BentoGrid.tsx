import clsx from 'clsx'
import type { HTMLAttributes, PropsWithChildren } from 'react'

type BentoGridProps = PropsWithChildren<HTMLAttributes<HTMLDivElement>>

export function BentoGrid({ className, children, ...rest }: BentoGridProps) {
  return (
    <div
      {...rest}
      className={clsx('bento-grid', className)}
    >
      {children}
    </div>
  )
}
