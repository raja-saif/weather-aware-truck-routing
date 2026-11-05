export function fmtDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  const d = Math.floor(minutes / 1440)
  const h = Math.floor((minutes % 1440) / 60)
  const m = minutes % 60
  if (d) return `${d}d ${h}h ${String(m).padStart(2, '0')}m`
  if (h) return `${h}h ${String(m).padStart(2, '0')}m`
  return `${m}m`
}

export function fmtMiles(mi: number): string {
  return `${Math.round(mi).toLocaleString()} mi`
}

const dateTime = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})
const timeOnly = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })
const tzName =
  new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })
    .formatToParts(new Date())
    .find((p) => p.type === 'timeZoneName')?.value ?? ''

export function fmtDateTime(d: Date | string | number): string {
  return dateTime.format(new Date(d))
}

export function fmtTime(d: Date | string | number): string {
  return timeOnly.format(new Date(d))
}

export const localTzName = tzName

/** Value for <input type="datetime-local"> in local time. */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function nextQuarterHour(from = new Date()): Date {
  const d = new Date(from)
  d.setSeconds(0, 0)
  d.setMinutes(Math.ceil((d.getMinutes() + 1) / 15) * 15)
  return d
}

export function fmtNumber(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
