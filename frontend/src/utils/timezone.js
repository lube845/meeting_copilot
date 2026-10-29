/**
 * Dayjs timezone utility
 */
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

dayjs.extend(utc)
dayjs.extend(timezone)

// 默认时区
export const getTimezone = () => {
  if (typeof window !== 'undefined' && window.__TZ__) {
    return window.__TZ__
  }
  return 'Asia/Shanghai'
}

export function formatDate(date, formatStr = 'YYYY-MM-DD HH:mm:ss') {
  if (!date) return '-'
  return dayjs.tz(date, getTimezone()).format(formatStr)
}

export function formatDateOnly(date) {
  if (!date) return '-'
  return dayjs.tz(date, getTimezone()).format('YYYY-MM-DD')
}

export function now() {
  return dayjs().tz(getTimezone())
}

export function startOfDay(date) {
  return dayjs.tz(date, getTimezone()).startOf('day')
}

export function endOfDay(date) {
  return dayjs.tz(date, getTimezone()).endOf('day')
}

export default {
  formatDate,
  formatDateOnly,
  now,
  startOfDay,
  endOfDay,
  dayjs,
  getTimezone
}