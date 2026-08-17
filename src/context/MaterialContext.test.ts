/**
 * parseCsv / stepsToCsv unit tests (pure functions exported from
 * MaterialContext.tsx). Importing the module pulls in React and
 * hardware-api.ts (import.meta.env) but renders nothing, so the 'node'
 * environment is enough.
 */
import { describe, it, expect } from 'vitest'
import { parseCsv, stepsToCsv } from '@/context/MaterialContext'
import type { CureStep } from '@/context/MaterialContext'

const HEADER = 'Step,Process,Temperature,Time,TimerMode,UVIntensity,UVStart,UVRampPercent,CoolingMode'
const csv = (...rows: string[]) => [HEADER, ...rows].join('\n')
const legacy = (...rows: string[]) => ['Step,Process,Temperature,Time,Intensity', ...rows].join('\n')

describe('parseCsv - valid programs', () => {
  it('parses a legacy 5-column CSV', () => {
    const r = parseCsv(legacy('1,Heating,50,10,', '2,Cure,60,20,50', '3,Cooling,40,,'))
    expect(r.errors).toEqual([])
    expect(r.steps).not.toBeNull()
    expect(r.steps!.length).toBe(3)
    expect(r.steps![0]).toMatchObject({ step: 1, process: 'Heating', temperature: 50, time: 10 })
    // legacy 5th column (Intensity) is NOT the UV intensity column - uvIntensity stays unset
    expect(r.steps![1].uvIntensity).toBeUndefined()
    expect(r.steps![2]).toMatchObject({ process: 'Cooling', temperature: 40, time: 0, coolingMode: 'medium' })
  })

  it('parses the full 9-column CSV with UV fields and cooling mode', () => {
    const r = parseCsv(csv(
      '1,Heating,50,10,,,,,',
      '2,Cure,60,30,on-ramp,45,at-start,50,',
      '3,Cooling,40,,,,,,fast',
    ))
    expect(r.errors).toEqual([])
    const s = r.steps!
    expect(s[1]).toMatchObject({
      process: 'Cure', temperature: 60, time: 30,
      timerMode: 'on-ramp', uvIntensity: 45, uvStartMode: 'at-start', uvRampPercent: 50,
    })
    expect(s[2].coolingMode).toBe('fast')
  })

  it('accepts a Bleacher step up to 720 minutes', () => {
    const r = parseCsv(csv('1,Bleacher,50,720,,30,,,'))
    expect(r.errors).toEqual([])
    expect(r.steps![0].time).toBe(720)
  })

  it('accepts a Nitrogen -> Cure -> Cooling program (N2 blank fields)', () => {
    const r = parseCsv(csv('1,Nitrogen,,,,,,,', '2,Cure,50,10,,30,,,', '3,Cooling,40,,,,,,slow'))
    expect(r.errors).toEqual([])
    expect(r.steps![0]).toMatchObject({ process: 'Nitrogen', temperature: null, time: 0 })
    expect(r.steps![2].coolingMode).toBe('slow')
  })

  it('defaults blank temperature to 40 (heat type) / 25 (cooling)', () => {
    // A blank cooling temp becomes 25 which is BELOW COOL_MIN_TEMP=30 - it is
    // still accepted because the range check only runs on non-blank values.
    const r = parseCsv(csv('1,Heating,,10,,,,,', '2,Cooling,,,,,,,'))
    expect(r.errors).toEqual([])
    expect(r.steps![0].temperature).toBe(40)
    expect(r.steps![1].temperature).toBe(25)
  })

  it('accepts a heat-type step below 30 (OFF / no-heat mode, 0.4.9 semantics)', () => {
    // 15-29 C on Heating/Drying/Cure/Bleacher = run without the heater.
    const r = parseCsv(csv('1,Cure,25,10,,30,,,', '2,Heating,15,5,,,,,', '3,Drying,29,5,,,,,'))
    expect(r.errors).toEqual([])
    expect(r.steps!.map(s => s.temperature)).toEqual([25, 15, 29])
  })

  it('no-heat steps neither violate nor advance the rising-temperature chain', () => {
    // 60 -> 25 (OFF cure) -> 65: the OFF step is skipped for the sequence rule
    const r = parseCsv(csv('1,Heating,60,10,,,,,', '2,Cure,25,10,,30,,,', '3,Heating,65,10,,,,,'))
    expect(r.errors).toEqual([])
  })
})

describe('parseCsv - rejections', () => {
  it('rejects heat-type temperature below the no-heat floor (15) and above 80', () => {
    expect(parseCsv(csv('1,Heating,14,10,,,,,')).errors[0]).toMatch(/Invalid temperature "14" \(must be 15-80 for Heating\)/)
    expect(parseCsv(csv('1,Cure,81,10,,30,,,')).errors[0]).toMatch(/must be 15-80/)
  })

  it('rejects cooling temperature outside 30-75', () => {
    expect(parseCsv(csv('1,Heating,60,10,,,,,', '2,Cooling,29,,,,,,')).errors[0]).toMatch(/must be 30-75 for Cooling/)
    expect(parseCsv(csv('1,Cooling,76,,,,,,')).errors[0]).toMatch(/must be 30-75 for Cooling/)
  })

  it('rejects a cooling target that is not >= 5 C below the previous step', () => {
    const r = parseCsv(csv('1,Heating,50,10,,,,,', '2,Cooling,46,,,,,,'))
    expect(r.steps).toBeNull()
    expect(r.errors[0]).toMatch(/Cooling target \(46°C\) must be at least 5°C below the previous step \(50°C\)/)
    // exactly 5 below is fine
    expect(parseCsv(csv('1,Heating,50,10,,,,,', '2,Cooling,45,,,,,,')).errors).toEqual([])
  })

  it('rejects a lower temperature after a higher one without a Cooling step', () => {
    const r = parseCsv(csv('1,Heating,60,10,,,,,', '2,Drying,50,10,,,,,'))
    expect(r.errors[0]).toMatch(/cannot be lower than the previous step/)
    // ...but a Cooling step in between resets the chain
    expect(parseCsv(csv('1,Heating,60,10,,,,,', '2,Cooling,40,,,,,,', '3,Drying,50,10,,,,,')).errors).toEqual([])
  })

  it('rejects time > 120 for non-Bleacher and > 720 for Bleacher, and time < 1', () => {
    expect(parseCsv(csv('1,Heating,50,121,,,,,')).errors[0]).toMatch(/Invalid time "121" \(must be 1-120\)/)
    expect(parseCsv(csv('1,Cure,50,200,,30,,,')).errors[0]).toMatch(/must be 1-120/)
    expect(parseCsv(csv('1,Bleacher,50,721,,30,,,')).errors[0]).toMatch(/must be 1-720/)
    expect(parseCsv(csv('1,Heating,50,0,,,,,')).errors[0]).toMatch(/Invalid time "0"/)
    expect(parseCsv(csv('1,Heating,50,abc,,,,,')).errors[0]).toMatch(/Invalid time "abc"/)
  })

  it('rejects UV intensity below 10 or above 100', () => {
    expect(parseCsv(csv('1,Cure,50,10,,9,,,')).errors[0]).toMatch(/Invalid UV intensity "9" \(must be 10-100\)/)
    expect(parseCsv(csv('1,Bleacher,50,10,,101,,,')).errors[0]).toMatch(/must be 10-100/)
    expect(parseCsv(csv('1,Cure,50,10,,10,,,')).errors).toEqual([])
  })

  it('rejects an unknown process and short rows', () => {
    const r = parseCsv(csv('1,Baking,50,10,,,,,', '2,Heating,50'))
    expect(r.steps).toBeNull()
    expect(r.errors).toEqual([
      expect.stringMatching(/Row 1: Invalid process "Baking"/),
      expect.stringMatching(/Row 2: Not enough columns/),
    ])
  })

  it('rejects an empty / header-only / header-less input', () => {
    expect(parseCsv('').steps).toBeNull()
    expect(parseCsv(HEADER).errors[0]).toMatch(/header row and at least one data row/)
    expect(parseCsv('a,b,c,d\n1,Heating,50,10').errors[0]).toMatch(/Missing required header/)
  })

  it('enforces the nitrogen rules', () => {
    // N2 must be followed by Cure/Bleacher and vented by Cooling
    expect(parseCsv(csv('1,Nitrogen,,,,,,,', '2,Heating,50,10,,,,,')).errors).toEqual(
      expect.arrayContaining([expect.stringMatching(/After nitrogen, only Cure or Bleaching/)]))
    expect(parseCsv(csv('1,Nitrogen,,,,,,,', '2,Cure,50,10,,30,,,')).errors).toEqual(
      expect.arrayContaining([expect.stringMatching(/Nitrogen must be vented/)]))
    // max 2 N2 steps
    const r = parseCsv(csv('1,Nitrogen,,,,,,,', '2,Cure,50,10,,30,,,', '3,Cooling,40,,,,,,',
      '4,Nitrogen,,,,,,,', '5,Cure,50,10,,30,,,', '6,Cooling,40,,,,,,',
      '7,Nitrogen,,,,,,,', '8,Cure,50,10,,30,,,', '9,Cooling,40,,,,,,'))
    expect(r.errors).toEqual(expect.arrayContaining([expect.stringMatching(/maximum of 2 nitrogen/)]))
  })

  it('returns steps: null whenever any error exists', () => {
    const r = parseCsv(csv('1,Heating,50,10,,,,,', '2,Heating,200,10,,,,,'))
    expect(r.steps).toBeNull()
    expect(r.errors.length).toBe(1)
  })
})

describe('stepsToCsv <-> parseCsv round trip', () => {
  const program = csv(
    '1,Nitrogen,,,,,,,',
    '2,Cure,50,20,on-target,40,at-target,,',
    '3,Cooling,40,,,,,,fast',
    '4,Heating,55,10,,,,,',
    '5,Drying,60,15,,,,,',
    '6,Bleacher,65,300,on-ramp,60,at-start,,',
    '7,Cooling,35,,,,,,slow',
  )

  it('is stable: parse(csv(parse(x))) equals parse(x)', () => {
    const first = parseCsv(program)
    expect(first.errors).toEqual([])
    const out = stepsToCsv(first.steps!)
    const second = parseCsv(out)
    expect(second.errors).toEqual([])
    expect(second.steps).toEqual(first.steps)
    // and the text itself is a fixed point
    expect(stepsToCsv(second.steps!)).toBe(out)
  })

  it('emits blank fields for Nitrogen/Cooling and defaults for UV steps', () => {
    const steps: CureStep[] = [
      { step: 1, process: 'Nitrogen', temperature: null, intensity: null, time: 0 },
      { step: 2, process: 'Cure', temperature: 50, intensity: null, time: 10 },
      { step: 3, process: 'Cooling', temperature: 40, intensity: null, time: 0 },
    ]
    const lines = stepsToCsv(steps).split('\n')
    expect(lines[0]).toBe(HEADER)
    expect(lines[1]).toBe('1,Nitrogen,,,,,,,')
    expect(lines[2]).toBe('2,Cure,50,10,on-target,30,at-target,,')
    expect(lines[3]).toBe('3,Cooling,40,,,,,,medium')
  })
})
