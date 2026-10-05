import { getRepo } from "@/lib/repo";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  // Reports the health of whichever storage backend is active (Postgres when a
  // connection succeeds, otherwise the local JSON store).
  const repo = await getRepo();
  const ok = await repo.probe();
  return Response.json({ ok, backend: repo.backend }, { status: ok ? 200 : 500 });
}
