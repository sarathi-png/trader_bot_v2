/**
 * Runtime check of the auth primitives (Web Crypto only, no DB/network).
 * Run with:  node --experimental-strip-types check_auth.ts
 *
 * env is set before the dynamic import so the module reads it at call time.
 */
process.env.API_PASSWORD = "correct-horse-battery-staple";
process.env.SESSION_SECRET = "a-separate-session-secret";

const auth = await import("./src/lib/auth.ts");

let pass = 0;
let fail = 0;
function expect(name: string, actual: boolean, wanted: boolean) {
  const ok = actual === wanted;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}  -> got ${actual}, want ${wanted}`);
  ok ? pass++ : fail++;
}

// ---- constant-time comparison ----
expect("equal strings match", auth.timingSafeEqual("abc123", "abc123"), true);
expect("different strings differ", auth.timingSafeEqual("abc123", "abc124"), false);
expect("different lengths differ", auth.timingSafeEqual("abc", "abcdef"), false);
expect("empty vs empty", auth.timingSafeEqual("", ""), true);
expect("prefix does not match", auth.timingSafeEqual("secret", "secre"), false);

// ---- password ----
expect("correct password accepted", auth.passwordMatches("correct-horse-battery-staple"), true);
expect("wrong password rejected", auth.passwordMatches("wrong"), false);
expect("empty password rejected", auth.passwordMatches(""), false);
expect("missing password rejected", auth.passwordMatches(null), false);

// ---- bearer extraction ----
expect("bearer parsed", auth.bearerFrom("Bearer abc123") === "abc123", true);
expect("bearer case-insensitive", auth.bearerFrom("bearer abc123") === "abc123", true);
expect("non-bearer ignored", auth.bearerFrom("Basic xyz"), null);
expect("absent header ignored", auth.bearerFrom(null), null);

// ---- session signing ----
const secret = auth.sessionSecret();
const future = Date.now() + 60_000;
const past = Date.now() - 60_000;
const good = await auth.signSession(future, secret);

expect("valid session verifies", await auth.verifySession(good, secret), true);
expect("expired session rejected", await auth.verifySession(await auth.signSession(past, secret), secret), false);
expect("wrong secret rejected", await auth.verifySession(good, "attacker-secret"), false);
expect("tampered payload rejected", await auth.verifySession(good.replace(/^v1\.\d+/, "v1.99999999999999"), secret), false);
expect("tampered signature rejected", await auth.verifySession(`${good.slice(0, -2)}00`, secret), false);
expect("malformed token rejected", await auth.verifySession("garbage", secret), false);
expect("empty token rejected", await auth.verifySession("", secret), false);
expect("null token rejected", await auth.verifySession(null, secret), false);

// ---- fail closed when unconfigured ----
expect("auth configured with password", auth.authConfigured(), true);
delete process.env.API_PASSWORD;
delete process.env.SESSION_SECRET;
expect("auth unconfigured without password", auth.authConfigured(), false);
expect("no password means no match", auth.passwordMatches("correct-horse-battery-staple"), false);

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);