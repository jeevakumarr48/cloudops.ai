# 0005. Server-side sessions in a first-party cookie, not JWTs

- Status: Accepted
- Date: 2026-11-26 (recorded)

## Context

The console and API are separate Vercel projects. Calling the API cross-origin
would need third-party cookies (blocked by browsers) or a bearer token in
JavaScript-readable storage (exposed to any XSS).

## Decision

The console calls `/api` on its own origin, and `frontend/vercel.json` rewrites
to the API, so the session cookie is first-party. The cookie is `HttpOnly`,
`Secure` and `SameSite=Lax`. It holds a random token; the database stores only
its SHA-256 digest, so a database leak does not yield usable sessions. Logout
deletes the row. Passwords use Argon2id with rehash on login. State-changing
requests must come from an allowed `Origin` (or `Sec-Fetch-Site: same-origin`),
which covers CSRF. Login and registration are rate-limited per IP and per
email, and auth events go to an audit log.

## Consequences

- Revocation is immediate, which JWTs cannot do without a denylist.
- One database read per authenticated request; acceptable at this scale.
- The API is not meant for third-party browser clients.

## Alternatives considered

- **JWT in localStorage.** Rejected: readable by injected scripts, no revocation.
- **Hosted auth (Auth0, Clerk).** Rejected for cost and an extra dependency at
  this size; the session model would move over cleanly if needed.
