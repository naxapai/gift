interface MetricTileProps {
  label: string
  value: string | number
}

export function MetricTile({ label, value }: MetricTileProps) {
  return (
    <div className="rounded-xl border border-dashed border-[#d6e2f3] bg-[rgba(255,255,255,0.72)] px-3 py-2">
      <div className="text-xs text-[#5f6874]">{label}</div>
      <div className="mt-1 text-[1.75rem] font-bold leading-none text-[#14151a] tabular-nums">{value}</div>
    </div>
  )
}
