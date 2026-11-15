# Security

This document describes what is implemented, how it was verified, and where the limits are.
It is updated as each phase lands.

## Reporting a vulnerability
Open a private security advisory on the GitHub repository. Do not file public issues for vulnerabilities.

## Implemented (Phase 1)

| Area | Control | Verified by |
|---|---|---|
| Passwords | Argon2id, per-password salt, rehash on parameter change. Minimum 10 characters. | `tests/test_auth.py::test_password_is_hashed_and_token_is_hashed` |
| Sessions | 256-bit random token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` in production). Only a SHA-256 hash is stored, so a database leak does not yield usable sessions. 7-day sliding expiry. Logout deletes the server-side session. | `test_logout_invalidates_server_side`, `scripts/e2e_web.py` |
| User enumeration | Wrong password and unknown email return identical responses; a dummy hash is verified so timing is similar. | `test_wrong_password_and_unknown_user_are_indistinguishable` |
| Brute force | Login limited per IP (20 / 15 min) and per email (8 / 15 min). Registration limited per IP. | `test_login_rate_limited` |
| CSRF | State-changing requests require `X-Requested-With: QuantaLens`, which cross-site forms cannot set. Combined with `SameSite=Lax`. | `test_csrf_header_required_for_state_changes` |
| Authorisation | Every data query is scoped by `user_id`. | `tests/test_overview.py::test_overview_counts_only_own_data` |
| Secrets | Read from environment only. `.env*` is git-ignored. `ANALYTICS_DATABASE_URL` and the LLM key are never sent to the browser. | Manual review; `.gitignore` |
| SQL role | Generated SQL will run as `quantalens_readonly`: SELECT on schema `qdata` only, read-only transactions, 15 s statement timeout, 10 connections. Cannot read `users` or `auth_sessions`. | `scripts/verify_readonly_role.py` (11 checks against Neon) |
| Headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`. API docs disabled in production. | Config review |
| Errors | Unhandled exceptions return a generic 500. Only the exception type is logged, never its message. | Config review |

## Known limits

- **Rate limiting is in memory** and per process. It resets on restart and is not shared across instances.
  Adequate for a single free-tier instance; a scaled deployment needs a shared store.
- **Client IP** for rate limiting is taken from `X-Forwarded-For`. A client that reaches the engine directly could
  spoof it, so the per-email limit exists as a second control.
- **Registration reveals whether an email is registered** (409). This is a usability trade-off and is rate limited.
- **No email verification or password reset yet.**
- **The Python runner is not yet built.** When it is, it will be a restricted subprocess, not a hardened
  sandbox. This document will describe exactly what it does and does not protect against.

## Planned (later phases)
SQL parsing and validation, dataset upload validation, prompt-injection handling, encrypted external
database credentials with SSRF protection, and a restricted Python runner.
