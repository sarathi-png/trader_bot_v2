/**
 * Feature flags, resolved from environment variables.
 * Sensitive capabilities default to OFF.
 */

function envBool(name: string, fallback: boolean): boolean {
  const v = process.env[name];
  if (v === undefined || v === "") return fallback;
  return v === "true" || v === "1";
}

export const flags = {
  /** Public Delta market data via REST (no credentials required). */
  deltaMarket: () => envBool("DELTA_MARKET_ENABLED", true),
  // NOTE: there is deliberately no `deltaAccountEnabled` here anymore. It used
  // to check environment variables only, while credentials can also be stored
  // encrypted in the database (Settings → Delta API) — which made the account
  // view show the demo wallet and the header show DISCONNECTED even with valid
  // saved keys. Use `deltaAccountConfigured()` from "@/lib/credentials" instead.
  paperTrading: () => envBool("PAPER_TRADING_ENABLED", true),
  liveExecution: () => envBool("LIVE_EXECUTION_ENABLED", false),
  orderbook: () => envBool("ORDERBOOK_ENABLED", true),
  strategyEngine: () => envBool("STRATEGY_ENGINE_ENABLED", true),
  autoSR: () => envBool("AUTO_S_R_ENABLED", true),
  journal: () => envBool("JOURNAL_ENABLED", true),
  analytics: () => envBool("ANALYTICS_ENABLED", true),
  tradingviewWebhook: () => envBool("TRADINGVIEW_WEBHOOK_ENABLED", false),
  telegram: () => envBool("TELEGRAM_ENABLED", false),
};

export const APP_VERSION = "1.0.0";
export const DELTA_REST_BASE =
  process.env.DELTA_REST_BASE || "https://api.india.delta.exchange";
export const DELTA_WS_URL =
  process.env.DELTA_WS_URL || "wss://socket.india.delta.exchange";
export const PAPER_FEE_RATE = 0.0005; // 0.05% taker per side
