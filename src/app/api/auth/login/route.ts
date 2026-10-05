/**
 * POST /api/auth/login — exchange the operator password for a session cookie.
 *
 * Fail closed: without API_PASSWORD the endpoint reports 503 and issues
 * nothing, so a misconfigured deployment cannot be logged into.
 */
import { NextResponse } from "next/server";
import {
  SESSION_COOKIE,
  SESSION_TTL_MS,
  authConfigured,
  passwordMatches,
  sessionSecret,
  signSession,
} from "@/lib/auth";
import { logAudit } from "@/lib/settings";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: Request) {
  if (!authConfigured()) {
    return Response.json(
      { error: "Authentication is not configured. Set API_PASSWORD and restart." },
      { status: 503 }
    );
  }

  let password = "";
  try {
    const body = (await req.json()) as { password?: unknown };
    password = typeof body.password === "string" ? body.password : "";
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  if (!passwordMatches(password)) {
    // Never record the attempted value.
    await logAudit("auth_login_failed", {});
    return Response.json({ error: "Invalid credentials." }, { status: 401 });
  }

  const token = await signSession(Date.now() + SESSION_TTL_MS, sessionSecret());
  await logAudit("auth_login_succeeded", {});

  const res = NextResponse.json({ ok: true, expiresInMs: SESSION_TTL_MS });
  res.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: Math.floor(SESSION_TTL_MS / 1000),
  });
  return res;
}