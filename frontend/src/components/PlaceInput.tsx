import { useEffect, useId, useRef, useState } from 'react'
import { searchPlaces } from '../api/client'
import type { PlaceInputValue, Suggestion } from '../api/types'

interface Props {
  label: string
  placeholder: string
  value: PlaceInputValue
  onChange: (v: PlaceInputValue) => void
  marker: 'start' | 'end'
}

/** Place search with debounced, cancellable suggestions and full keyboard support. */
export default function PlaceInput({ label, placeholder, value, onChange, marker }: Props) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Suggestion[]>([])
  const [active, setActive] = useState(-1)
  const [loading, setLoading] = useState(false)
  const picked = value.lat != null
  const query = value.label.trim()
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    window.clearTimeout(timer.current)
    if (picked || query.length < 2) {
      setItems([])
      setLoading(false)
      return
    }
    const ctrl = new AbortController()
    setLoading(true)
    timer.current = window.setTimeout(() => {
      searchPlaces(query, ctrl.signal)
        .then((r) => {
          setItems(r.results)
          setActive(r.results.length ? 0 : -1)
        })
        .catch((e) => {
          if (e.name !== 'AbortError') setItems([])
        })
        .finally(() => {
          if (!ctrl.signal.aborted) setLoading(false)
        })
    }, 220)
    return () => {
      ctrl.abort()
      window.clearTimeout(timer.current)
    }
  }, [query, picked])

  const choose = (s: Suggestion) => {
    onChange({ label: s.label, lat: s.lat, lon: s.lon })
    setOpen(false)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || !items.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => (a + 1) % items.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => (a - 1 + items.length) % items.length)
    } else if (e.key === 'Enter' && active >= 0) {
      e.preventDefault()
      choose(items[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const showList = open && !picked && query.length >= 2
  return (
    <div className="field place-field">
      <label htmlFor={id}>{label}</label>
      <div className={`place-input marker-${marker}`}>
        <input
          id={id}
          type="text"
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={value.label}
          role="combobox"
          aria-expanded={showList}
          aria-controls={`${id}-list`}
          aria-activedescendant={active >= 0 ? `${id}-opt-${active}` : undefined}
          onChange={(e) => {
            onChange({ label: e.target.value })
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={onKeyDown}
        />
        {picked && <span className="place-ok" title="Location selected" aria-label="Location selected">✓</span>}
      </div>
      {showList && (
        <ul id={`${id}-list`} role="listbox" className="suggestions">
          {loading && !items.length && <li className="suggestion muted">Searching…</li>}
          {!loading && !items.length && <li className="suggestion muted">No matches. Try a city, address or “lat, lon”.</li>}
          {items.map((s, i) => (
            <li
              key={`${s.label}-${i}`}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={`suggestion${i === active ? ' active' : ''}`}
              onMouseDown={(e) => {
                e.preventDefault()
                choose(s)
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span>{s.label}</span>
              {s.kind && <span className="kind">{s.kind}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
