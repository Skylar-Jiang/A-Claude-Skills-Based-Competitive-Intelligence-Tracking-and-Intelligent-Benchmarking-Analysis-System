import { CaretDown, Check, MagnifyingGlass } from '@phosphor-icons/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { FocusEvent, KeyboardEvent, ReactNode } from 'react'
import type { CatalogOption } from './catalogOptions'

type SearchableComboboxProps = {
  id: string
  label: string
  value: string
  options: CatalogOption[]
  onChange: (value: string) => void
  placeholder: string
  helperText: string
  required?: boolean
  icon?: ReactNode
}

export function SearchableCombobox({
  id,
  label,
  value,
  options,
  onChange,
  placeholder,
  helperText,
  required = false,
  icon,
}: SearchableComboboxProps) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const rootRef = useRef<HTMLDivElement>(null)
  const listboxId = `${id}-listbox`
  const helpId = `${id}-help`

  const filteredOptions = useMemo(() => {
    const query = value.trim().toLocaleLowerCase()
    if (!query) return options
    return options.filter((option) => {
      const searchable = `${option.value} ${option.group} ${option.keywords || ''}`.toLocaleLowerCase()
      if (/^[a-z0-9]{1,3}$/.test(query)) {
        return searchable.split(/[^a-z0-9]+/).some((token) => token === query || token.startsWith(query))
      }
      return searchable.includes(query)
    })
  }, [options, value])

  useEffect(() => {
    if (!open) return
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointer)
  }, [open])

  const choose = (option: CatalogOption) => {
    onChange(option.value)
    setOpen(false)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      setActiveIndex((current) => Math.min(current + 1, filteredOptions.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
      setActiveIndex((current) => current <= 0 ? filteredOptions.length - 1 : current - 1)
    } else if (event.key === 'Enter' && open) {
      if (activeIndex >= 0 && filteredOptions[activeIndex]) {
        event.preventDefault()
        choose(filteredOptions[activeIndex])
      } else {
        setOpen(false)
      }
    } else if (event.key === 'Escape') {
      event.preventDefault()
      setOpen(false)
    }
  }

  const handleBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false)
  }

  return (
    <div className="combobox-field" ref={rootRef} onBlur={handleBlur}>
      <label htmlFor={id}>
        <span>{label} {required && <b>*</b>}</span>
      </label>
      <div className={`searchable-combobox ${open ? 'is-open' : ''}`}>
        {icon && <span className="combobox-leading" aria-hidden="true">{icon}</span>}
        <input
          id={id}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-activedescendant={activeIndex >= 0 ? `${id}-option-${activeIndex}` : undefined}
          aria-describedby={helpId}
          autoComplete="off"
          required={required}
          value={value}
          placeholder={placeholder}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            onChange(event.target.value)
            setActiveIndex(-1)
            setOpen(true)
          }}
          onKeyDown={handleKeyDown}
        />
        <button
          type="button"
          className="combobox-toggle"
          aria-label={`${open ? '收起' : '展开'}${label}选项`}
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          <CaretDown weight="bold" aria-hidden="true" />
        </button>

        {open && (
          <div className="combobox-popover">
            <div className="combobox-search-hint">
              <MagnifyingGlass weight="bold" aria-hidden="true" />
              输入中文、英文或国家缩写进行筛选
            </div>
            <div id={listboxId} className="combobox-list" role="listbox" aria-label={`${label}常用选项`}>
              {filteredOptions.length ? filteredOptions.map((option, index) => {
                const showGroup = index === 0 || filteredOptions[index - 1]?.group !== option.group
                const selected = value === option.value
                return (
                  <div className="combobox-option-wrap" key={`${option.group}-${option.value}`}>
                    {showGroup && <div className="combobox-group" aria-hidden="true">{option.group}</div>}
                    <div
                      id={`${id}-option-${index}`}
                      className={`combobox-option ${activeIndex === index ? 'is-active' : ''}`}
                      role="option"
                      aria-selected={selected}
                      onMouseEnter={() => setActiveIndex(index)}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => choose(option)}
                    >
                      <span>{option.value}</span>
                      {selected && <Check weight="bold" aria-hidden="true" />}
                    </div>
                  </div>
                )
              }) : (
                <div className="combobox-empty">
                  <strong>没有找到完全匹配的常用选项</strong>
                  <span>可以保留“{value}”作为自定义内容。</span>
                </div>
              )}
            </div>
            <div className="combobox-custom-note">没有合适选项？当前输入会作为自定义内容提交。</div>
          </div>
        )}
      </div>
      <small id={helpId}>{helperText}</small>
    </div>
  )
}
