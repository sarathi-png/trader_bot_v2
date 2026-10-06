import { getAccountState } from "@/lib/account";
import { deltaAccountConfigured } from "@/lib/credentials";
import { flags } from "@/lib/flags";
import { getSettings } from "@/lib/settings";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  try {
    const [account, settings, deltaCreds] = await Promise.all([
      getAccountState(),
      getSettings(),
      deltaAccountConfigured(),
    ]);
    return Response.json({
      account,
      mode: settings.mode,
      liveArmed: settings.liveArmed,
      deltaAccountConfigured: deltaCreds,
      paperTradingEnabled: flags.paperTrading(),
    });
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Account data unavailable" },
      { status: 500 }
    );
  }
}
