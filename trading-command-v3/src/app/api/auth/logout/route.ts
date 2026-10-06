/**
 * POST /api/auth/logout — clear the session cookie.
 *
 * Deliberately unauthenticated: logging out must always succeed, including
 * when the session has already expired.
 */
import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth";
import { logAudit } from "@/lib/settings";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST() {
  await logAudit("auth_logout", {});
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
  return res;
}