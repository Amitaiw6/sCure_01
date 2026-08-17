/**
 * Process limits shared by the UI (CSV parser, program builder, cure page).
 *
 * These are PRODUCT rules for what a program may contain. The backend keeps
 * its own HARDWARE limits (server/app.py: HEAT_TARGET_MIN=30, TEMP_MAX=80,
 * COOL_TARGET_MIN=20, UV_INTENSITY_MIN=10) and re-validates every command;
 * they differ by design (e.g. cooling is 30-75 here, ≥20 on the server).
 * Pure constants — no React, no runtime imports (type-only import below).
 */
import type { ProcessType } from '@/context/MaterialContext'

// The heater driver refuses targets below 30°C (heating.target_min).
export const HEAT_MIN_TEMP = 30
// Single OFF notch below the heating floor (step=5): the step runs without heating.
export const NO_HEAT_MIN_TEMP = 25
export const HEAT_MAX_TEMP = 80
// Lowest coolable target: the chamber cannot cool below ambient (~30 °C).
export const COOL_MIN_TEMP = 30
export const COOL_MAX_TEMP = 75
// Heat-type steps MAY be entered as low as 15°C in CSV (no-heat mode).
export const NO_HEAT_FLOOR = 15
// Below led_power.min_intensity (10%) the LEDs stay dark.
export const UV_MIN = 10
export const UV_MAX = 100
export const TIME_MAX_MIN = 120
// Bleaching may run up to 12 hours.
export const TIME_MAX_MIN_BLEACH = 720

export const isUvProcess = (p: ProcessType) => p === 'Cure' || p === 'Bleacher'
export const isHeatType = (p: ProcessType) => p !== 'Cooling' && p !== 'Nitrogen'
