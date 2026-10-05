"use client";
import ChartPanel from "@/components/chart/ChartPanel";
import { OrderBookPanel, SignalPanel } from "@/components/panels";
import { Chip, KV, Panel, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtCompactUsd, fmtPct, fmtPrice, fmtUsd } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import { useMarket, useApp } from "@/stores";
import type { Analysis } from "@/lib/types";
import { cx } from "@/lib/format";

export default function ChartPage() {
  const { activeSymbol, timeframe, settings } = useApp();
  const ticker = useMarket((s) => s.tickers[activeSymbol]);

  const { data } = usePoll(
    () => api.get<{ analysis: Analysis }>(`/api/strategy/evaluate?symbol=${activeSymbol}&timeframe=${timeframe}`),
    20000, { deps: [activeSymbol, timeframe] }
  );
  const analysis = data?.analysis ?? null;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* symbol stat strip */}
      <div className="flex items-center gap-4 px-3 h-9 border-b border-edge bg-panel2/60 flex-none overflow-x-auto whitespace-nowrap">
        <span className="num text-[12px] font-semibold">{activeSymbol}</span>
        {ticker ? (
          <>
            <span className="num text-[13px]">${fmtPrice(ticker.price)}</span>
            <span className={cx("num text-[11px]", ticker.change24hPct >= 0 ? "text-up" : "text-dn")}>
              {fmtPct(ticker.change24hPct)}
            </span>
            <Stat label="24H HIGH" value={ticker.high24h !== null ? fmtPrice(ticker.high24h) : "N/A"} />
            <Stat label="24H LOW" value={ticker.low24h !== null ? fmtPrice(ticker.low24h) : "N/A"} />
            <Stat label="MARK" value={ticker.markPrice !== null ? fmtPrice(ticker.markPrice) : "N/A"} />
            {settings.modules.funding && (
              <Stat label="FUNDING / 8H" value={ticker.fundingRate !== null ? fmtPct(ticker.fundingRate, { decimals: 4 }) : "N/A"} />
            )}
            {settings.modules.funding && (
              <Stat label="OPEN INTEREST" value={ticker.openInterest !== null ? fmtCompactUsd(ticker.openInterest) : "N/A"} />
            )}
            {settings.modules.volume && (
              <Stat label="24H VOLUME" value={fmtUsd(ticker.volume24hUsd, { decimals: 0 })} />
            )}
            {ticker.source === "demo" && <Chip tone="warn">DEMO DATA</Chip>}
          </>
        ) : (
          <Skeleton className="h-4 w-64" />
        )}
      </div>

      {/* workspace */}
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 min-w-0 min-h-[420px]">
          <ChartPanel
            symbol={activeSymbol}
            timeframe={timeframe}
            analysis={analysis}
            interactive
            showObjectTree
            className="h-full"
          />
        </div>
        <div className="hidden lg:flex flex-col w-76 border-l border-edge gap-0 overflow-y-auto flex-none">
          {settings.modules.strategyScore && (
            <SignalPanel analysis={analysis} className="border-0 rounded-none border-b border-edge" />
          )}
          {settings.modules.orderbook && (
            <OrderBookPanel symbol={activeSymbol} className="border-0 rounded-none border-b border-edge" />
          )}
          {analysis && settings.modules.marketStructure && (
            <Panel title="MARKET STRUCTURE" className="border-0 rounded-none">
              <div className="p-3">
                <KV k="SEQUENCE" v={analysis.structureSeq.length ? analysis.structureSeq.join(" → ") : "N/A"} />
                <KV k="TREND" v={
                  <span className={analysis.trend === "BULLISH" ? "text-up" : analysis.trend === "BEARISH" ? "text-dn" : "text-warn"}>
                    {analysis.trend}
                  </span>
                } mono={false} />
                <p className="text-[9.5px] text-dim mt-2 leading-snug">
                  Structure labels are informational observations on closed candles, not certainty claims.
                </p>
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[9px] text-dim tracking-wider">{label}</span>
      <span className="num text-[11px] text-mut">{value}</span>
    </span>
  );
}
