import { getCandles } from "@/lib/market/service";
import { TIMEFRAMES, type Timeframe } from "@/lib/types";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const symbol = (url.searchParams.get("symbol") || "BTCUSD").toUpperCase();
  const tf = url.searchParams.get("timeframe") || "15m";
  const limit = Math.min(parseInt(url.searchParams.get("limit") || "300", 10) || 300, 500);
  if (!TIMEFRAMES.includes(tf as Timeframe)) {
    return Response.json({ error: `Unsupported timeframe: ${tf}` }, { status: 400 });
  }
  try {
    const { candles, source } = await getCandles(symbol, tf as Timeframe, limit);
    return Response.json({ symbol, timeframe: tf, candles, source });
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Candles unavailable" },
      { status: 502 }
    );
  }
}
