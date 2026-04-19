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
  disabled?: boolean
}

export function GmzSelect({ value, options, onChange, placeholder = 'Выберите', className, disabled = false }: GmzSelectProps) {
  return (
    <div className={clsx('gmz-select-wrap', className)}>
      <select
        className={clsx('gmz-select-native', disabled && 'is-disabled')}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{placeholder}</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <span className="gmz-select-native-caret" aria-hidden="true">▾</span>
    </div>
  )
}
