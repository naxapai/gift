import { useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'

export interface GmzOption {
  value: string
  label: string
}

interface GmzSelectProps {
  value: string
  options: GmzOption[]
  onChange: (value: string) => void
  placeholder?: string
  className?: string
}

export function GmzSelect({ value, options, onChange, placeholder = 'Выберите', className }: GmzSelectProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  const selected = useMemo(() => {
    return options.find((o) => o.value === value) || null
  }, [options, value])

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      const root = rootRef.current
      if (!root) return
      if (!root.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onEsc)
    }
  }, [])

  return (
    <div ref={rootRef} className={clsx('gmz-select-wrap', className)}>
      <button
        type="button"
        className={clsx('gmz-select-trigger', open && 'is-open')}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={selected ? 'text-[#14151a]' : 'text-[#9aa4b2]'}>{selected?.label || placeholder}</span>
        <span className={clsx('gmz-select-caret', open && 'is-open')} aria-hidden="true">
          ▾
        </span>
      </button>

      {open ? (
        <div className="gmz-select-menu" role="listbox">
          {options.map((opt) => {
            const active = opt.value === value
            return (
              <button
                key={opt.value}
                type="button"
                className={clsx('gmz-select-option', active && 'is-active')}
                onClick={() => {
                  onChange(opt.value)
                  setOpen(false)
                }}
              >
                {opt.label}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
