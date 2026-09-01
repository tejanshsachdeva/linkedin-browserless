# Automatic re-authentication — evaluation

**Status: implemented, tested, disabled by default. Not merged to `main`.**

This branch contains a working browserless re-authentication path: when the
LinkedIn session cookie expires, the service attempts one ordinary
username/password login to recover itself without human involvement.

It is on a branch rather than in `main` because testing showed it cannot
succeed in this environment — see [Result](#result). The code is kept
because the evaluation is the useful artifact.

---

## What it does

```
li_at expires
     │
     ▼
detected on the first redirect  ──►  credential marked INVALID
     │
     ▼
circuit breaker check ──► open? ──► stop, alert operator, return 503
     │ closed
     ▼
one login attempt (GET /login → extract CSRF → POST credentials)
     │
     ├── LinkedIn issues a session ──► validate cookie ──► promote ──► retry request
     │                                       └─ fails? roll back
     │
     └── LinkedIn asks for MFA / CAPTCHA / checkpoint
                    │
                    ▼
         STOP. Open breaker. Alert operator.
```

### Design rule

**Automate the ordinary login. Stop at any challenge. Never bypass one.**

`_classify_login_outcome` checks for challenge markers *before* looking for
a session cookie, and a challenge is terminal — it opens the circuit
breaker permanently rather than backing off and retrying. There is no
CAPTCHA solving, no verification-code interception, no retry past a
checkpoint. Those controls exist to require a human, and defeating them
would be both a security-control circumvention and a fast route to losing
the account.

`tests/unit/test_reauth.py::test_challenge_opens_breaker_permanently`
guards against a future change quietly turning this into a retry loop
against a security control.

### Circuit breaker

A failed scrape costs one HTTP request. A failed *login* is a security
event on the account, and repeated automated logins escalate toward
restriction. The breaker enforces:

| Guard | Default |
|---|---|
| Attempts per expiry event | 1 |
| Cooldown between attempts | 3600s |
| Hard daily cap | 3 |
| State after a challenge | OPEN — stops entirely until an operator resets |
| Concurrent attempts | Serialized by lock: N concurrent 503s → 1 login |

A recovered cookie is validated against LinkedIn *before* being promoted,
with rollback on failure — otherwise a successful-looking recovery could
swap one broken credential for another.

---

## Result

Tested against a genuinely expired session:

```json
{
  "recovered": false,
  "reason": "linkedin_verification_required",
  "detail": "Login page itself presented a challenge (captcha)",
  "breaker_state": "open",
  "breaker_opened_reason": "verification_required",
  "attempts_today": 1
}
```

LinkedIn served a CAPTCHA **on the login page itself** — before credentials
were submitted. That is their anti-automation layer responding to the shape
of the request, not a response to invalid credentials. Nothing about the
login flow can be adjusted to avoid it; the only way past is defeating the
CAPTCHA.

This was tested from a residential IP. A datacenter IP (the actual
deployment target) is a strictly harder case.

The breaker opened correctly and stopped after one attempt, which is the
behaviour it was built for.

---

## Why it isn't in `main`

1. **It cannot succeed here.** Shipping a recovery path that always fails
   adds moving parts without adding reliability.
2. **It requires storing the account password.** A session cookie can be
   revoked from LinkedIn's settings; a leaked password is full account
   access. That is a materially larger secret to hold for a path with no
   demonstrated success.
3. **Each attempt is a login event on the account.** Non-zero cost, zero
   expected benefit.

`main` uses runtime credential rotation instead: expiry is detected and
classified, callers receive a 503 with `Retry-After` rather than a 500, and
a fresh cookie is installed through an authenticated endpoint that
validates before promoting. It takes effect on the next request with no
redeploy.

Everything around credential capture is automated — detection,
classification, alerting, validation, storage, hot-swap, and retry of the
original request. Capture itself is manual, by LinkedIn's design.

---

## Running it

```bash
REAUTH_ENABLED=true
LINKEDIN_EMAIL=you@example.com
LINKEDIN_PASSWORD=...
REAUTH_COOLDOWN_SECONDS=3600
REAUTH_MAX_ATTEMPTS_PER_DAY=3
```

Trigger one attempt manually:

```bash
curl -X POST ".../admin/session/recover?force=true" -H "X-Admin-Key: $KEY"
```

`force=true` bypasses the cooldown and daily cap. It does **not** bypass
the challenge stop. Use it once, not in a loop — the cooldown is the guard
against exactly that.

After a challenge, the breaker stays open by design. Recover by hand:

1. Complete the verification in a browser
2. Console: `copy(document.cookie.match(/li_at=([^;]+)/)?.[1])`
3. `POST /admin/session/rotate` with the value
4. `POST /admin/session/breaker/reset` to re-arm

---

## Files

| File | Purpose |
|---|---|
| `app/client/reauth.py` | Single login attempt + outcome classification |
| `app/services/session_recovery.py` | Orchestration + circuit breaker |
| `app/services/session_alerter.py` | Webhook/log alerting on failure |
| `tests/unit/test_reauth.py` | 16 tests, no network or credentials required |

### Fragility

The login endpoint path and form field names are internal LinkedIn web-app
details, not a published API, and change without notice. They are
centralized as constants at the top of `reauth.py` — if this starts
returning `login_form_not_recognized`, that is the one place to re-inspect
in DevTools and patch.

---

## Legal note

Automated access to LinkedIn violates their User Agreement. This branch was
built for evaluation on a personal account. It deliberately does not
circumvent MFA, CAPTCHA, or device-verification controls.
