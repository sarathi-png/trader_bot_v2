import { getRepo } from "@/lib/repo";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const rows = await (await getRepo()).listAudit(120);
  return Response.json({ events: rows });
}
