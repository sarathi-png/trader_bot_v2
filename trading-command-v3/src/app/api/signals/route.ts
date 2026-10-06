import { getRepo } from "@/lib/repo";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const symbol = url.searchParams.get("symbol");
  const limit = Math.min(parseInt(url.searchParams.get("limit") || "200", 10) || 200, 500);
  const rows = await (await getRepo()).listSignals({ symbol: symbol ?? undefined, limit });
  return Response.json({ signals: rows });
}

export async function PATCH(req: Request) {
  // Manual override of a signal outcome (e.g. mark as invalidated).
  let body: { id?: string; outcome?: string };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }
  if (!body.id || !["MANUAL_OVERRIDE", "INVALIDATED", "TRIGGERED"].includes(body.outcome ?? "")) {
    return Response.json({ error: "Invalid override" }, { status: 400 });
  }
  await (await getRepo()).updateSignal(body.id, {
    outcome: body.outcome as "MANUAL_OVERRIDE",
  });
  return Response.json({ ok: true });
}
