/**
 * Frontend DCF recalculation engine.
 * Mirrors the Python valuation_engine.py math exactly.
 * Runs in real-time as the user moves sensitivity sliders.
 *
 * No backend round-trips needed for sensitivity analysis.
 */

import { FundamentalData, SensitivityOverrides } from '../types/valuation'

export interface LiveValuation {
  projectedFcfs: number[]
  pvFcfs: number[]
  terminalValue: number
  pvTerminalValue: number
  enterpriseValue: number
  equityValue: number
  intrinsicPrice: number
}

/**
 * Project FCF for n years at constant growth rate.
 */
function projectFCFs(baseFCF: number, growthRate: number, years: number): number[] {
  return Array.from({ length: years }, (_, i) => baseFCF * Math.pow(1 + growthRate, i + 1))
}

/**
 * Discount cash flows to present value.
 */
function presentValues(cashFlows: number[], discountRate: number): number[] {
  return cashFlows.map((cf, t) => cf / Math.pow(1 + discountRate, t + 1))
}

/**
 * Gordon Growth Model terminal value.
 * TV = FCF_n × (1 + g) / (WACC - g)
 */
function gordonTV(lastFCF: number, terminalGrowth: number, wacc: number): number {
  const spread = Math.max(wacc - terminalGrowth, 0.001)
  return lastFCF * (1 + terminalGrowth) / spread
}

/**
 * Full frontend DCF computation.
 * Called on every slider change — pure math, no network.
 */
export function computeFrontendDCF(
  f: FundamentalData,
  overrides: SensitivityOverrides,
): LiveValuation {
  const wacc = overrides.wacc / 100
  const growthRate = overrides.growthRate / 100
  const terminalGrowth = Math.min(overrides.terminalGrowth / 100, wacc - 0.001)
  const years = f.assumptions.projection_years || 5

  // Project FCFs
  const projectedFcfs = projectFCFs(f.base_fcf, growthRate, years)

  // Discount to PV
  const pvFcfs = presentValues(projectedFcfs, wacc)

  // Terminal Value (end of year 5)
  const tv = gordonTV(projectedFcfs[years - 1], terminalGrowth, wacc)
  const pvTV = tv / Math.pow(1 + wacc, years)

  // Enterprise Value
  const enterpriseValue = pvFcfs.reduce((a, b) => a + b, 0) + pvTV

  // Equity Value
  const equityValue = enterpriseValue - f.net_debt

  // Intrinsic price per share
  const intrinsicPrice = f.shares_outstanding > 0
    ? equityValue / f.shares_outstanding
    : 0

  return {
    projectedFcfs,
    pvFcfs,
    terminalValue: tv,
    pvTerminalValue: pvTV,
    enterpriseValue,
    equityValue,
    intrinsicPrice,
  }
}
