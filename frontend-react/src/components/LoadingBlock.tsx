export function LoadingBlock({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-slate-200/80 ${className}`.trim()} />
}
