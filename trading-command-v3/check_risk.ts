/**
 * Runtime check of the pure risk evaluator (no DB, no network).
 * Run with:  node --experimental-strip-types check_risk.ts
 */
import { evaluateOrderRisk, normalizeRiskLimits, type RiskContext } from "./src/lib/risk.ts";

const limits = { maxDailyLoss: 200, maxOrderValue: 5000, maxLeverage: 10, maxOpenPositions: 2 };
const base: RiskContext = {
  limits,
  openSymbols: [],
  currentNotional: 0,
  equity: 100_000,
  dailyRealizedPnl: 0,
};

let pass = 0;
let fail = 0;
function check(name: string, expectedAllowed: boolean, expectedCode: string, ctx: Partial<RiskContext> = {}, input = { symbol: "BTCUSD", qty: 1, price: 1000, reduceOnly: false }) {
  const v = evaluateOrderRisk(input, { ...base, ...ctx });
  const ok = v.allowed === expectedAllowed && (!expectedAllowed ? v.code === expectedCode : true);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}  -> allowed=${v.allowed} code=${v.code}`);
  ok ? pass++ : fail++;
}

// baseline: a normal small order must pass
check("normal order allowed", true, "ok");

// max order value
check("order value over cap", false, "max_order_value", {}, { symbol: "BTCUSD", qty: 10, price: 1000, reduceOnly: false });

// daily loss limit
check("daily loss breached", false, "max_daily_loss", { dailyRealizedPnl: -250 });

// unknown daily P&L must FAIL CLOSED - the critical one
check("unknown daily P&L fails closed", false, "daily_pnl_unavailable", { dailyRealizedPnl: null });

// max open positions (new symbol)
check("open position cap", false, "max_open_positions", { openSymbols: ["ETHUSD", "SOLUSD"] });
// adding to an existing symbol is still allowed
check("add to existing symbol allowed", true, "ok", { openSymbols: ["BTCUSD", "ETHUSD"] });
// reduce-only bypasses the position cap
check("reduce-only bypasses position cap", true, "ok", { openSymbols: ["ETHUSD", "SOLUSD"] }, { symbol: "DOGEUSD", qty: 1, price: 10, reduceOnly: true });

// leverage
check("leverage cap", false, "max_leverage", { currentNotional: 1_050_000 }, { symbol: "BTCUSD", qty: 1, price: 1000, reduceOnly: false });

// invalid input
check("zero qty rejected", false, "invalid_qty", {}, { symbol: "BTCUSD", qty: 0, price: 1000, reduceOnly: false });
check("negative price rejected", false, "invalid_price", {}, { symbol: "BTCUSD", qty: 1, price: -5, reduceOnly: false });
check("missing symbol rejected", false, "invalid_symbol", {}, { symbol: "", qty: 1, price: 10, reduceOnly: false });

// limit normalisation: nonsense settings must not disable caps
const n = normalizeRiskLimits({ maxOrderValue: 0, maxDailyLoss: -5, maxLeverage: 9999, maxOpenPositions: 0 });
const normalised = n.maxOrderValue > 0 && n.maxDailyLoss > 0 && n.maxLeverage <= 50 && n.maxOpenPositions > 0;
console.log(`${normalised ? "PASS" : "FAIL"}  normalizeRiskLimits clamps nonsense -> ${JSON.stringify(n)}`);
normalised ? pass++ : fail++;

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);