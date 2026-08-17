import { describe, it, expect } from 'vitest'
import {
  HEAT_MIN_TEMP, NO_HEAT_MIN_TEMP, HEAT_MAX_TEMP, COOL_MIN_TEMP, COOL_MAX_TEMP,
  NO_HEAT_FLOOR, UV_MIN, UV_MAX, TIME_MAX_MIN, TIME_MAX_MIN_BLEACH,
  isUvProcess, isHeatType,
} from '@/lib/limits'

describe('limits constants (safety invariant §7: values unchanged)', () => {
  it('has the documented values 30/25/80/30/75/15/10/100/120/720', () => {
    expect(HEAT_MIN_TEMP).toBe(30)
    expect(NO_HEAT_MIN_TEMP).toBe(25)
    expect(HEAT_MAX_TEMP).toBe(80)
    expect(COOL_MIN_TEMP).toBe(30)
    expect(COOL_MAX_TEMP).toBe(75)
    expect(NO_HEAT_FLOOR).toBe(15)
    expect(UV_MIN).toBe(10)
    expect(UV_MAX).toBe(100)
    expect(TIME_MAX_MIN).toBe(120)
    expect(TIME_MAX_MIN_BLEACH).toBe(720)
  })

  it('keeps ordering sane', () => {
    expect(NO_HEAT_FLOOR).toBeLessThan(NO_HEAT_MIN_TEMP)
    expect(NO_HEAT_MIN_TEMP).toBeLessThan(HEAT_MIN_TEMP)
    expect(HEAT_MIN_TEMP).toBeLessThan(HEAT_MAX_TEMP)
    expect(COOL_MIN_TEMP).toBeLessThan(COOL_MAX_TEMP)
    expect(COOL_MAX_TEMP).toBeLessThanOrEqual(HEAT_MAX_TEMP)
    expect(TIME_MAX_MIN).toBeLessThan(TIME_MAX_MIN_BLEACH)
  })
})

describe('process helpers', () => {
  it('isUvProcess is true only for Cure and Bleacher', () => {
    expect(isUvProcess('Cure')).toBe(true)
    expect(isUvProcess('Bleacher')).toBe(true)
    for (const p of ['Heating', 'Drying', 'Cooling', 'Nitrogen'] as const) {
      expect(isUvProcess(p)).toBe(false)
    }
  })

  it('isHeatType is false only for Cooling and Nitrogen', () => {
    for (const p of ['Heating', 'Drying', 'Cure', 'Bleacher'] as const) {
      expect(isHeatType(p)).toBe(true)
    }
    expect(isHeatType('Cooling')).toBe(false)
    expect(isHeatType('Nitrogen')).toBe(false)
  })
})
