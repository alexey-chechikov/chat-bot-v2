# GinArea API Notes

## 1. Public endpoints used

- `POST /accounts/login`
- `POST /accounts/twoFactor`
- `GET /bots`
- `GET /bots/{bot_id}`
- `GET /bots/{bot_id}/params`
- `PUT /bots/{bot_id}/params`
- `GET /bots/{bot_id}/stat`
- `GET /bots/{bot_id}/stat/history`

OpenAPI reference was expected in `openapi.yaml` per TZ, but no such file was present in the workspace during implementation. The module therefore follows the endpoint contracts explicitly stated in the TZ plus the observed response shapes captured in sanitized fixtures.

## 1a. Control endpoints (RE'd 2026-05-17 via operator DevTools)

- `PUT /bots/{bot_id}/start`
  - request body: `{}` (empty JSON)
  - effect: starts a paused/failed bot — same flow as UI ▶ play / restart
  - implemented: `BotsAPI.resume_bot(bot_id)`
- `PUT /bots/{bot_id}/pause` (HYPOTHESIZED, not yet captured)
  - inferred from `/start` symmetry; operator capture pending

**CRITICAL: do NOT use `PUT /bots/{id}/params` with `p=false/true` as a
pause/resume mechanism.** That endpoint edits the bot's default config —
not runtime control. Setting `p=false` via params transitions bot to
status=FAILED(10), confirmed by `scripts/_diag_tb_pause_strategies.py`
2026-05-17 incident on TB testbed. Use the `/start` (resume) and future
`/pause` endpoints instead.

## 2. Private endpoints (RE'd 2026-04-30)

- `POST /api/bots/{bot_id}/tests`
  - request body: `{"dateFrom": "<ISO8601>", "dateTo": "<ISO8601>"}`
  - response: Test object with `status=0`, `params` snapshot, `stat=null`, `statHistory=[]`
- `GET /api/bots/{bot_id}/tests?interval=1h&maxCount=150`
  - response: list of Test objects
  - finished tests have `status=14`, populated `stat`, and populated `statHistory`

Polling pattern:
- UI behavior observed in RE: repeat `GET /tests` every 1-2 seconds until `status==14`
- `BacktestAPI.wait_for_finished()` follows the same high-level pattern with configurable polling interval

Status enum:
- `0=Created`
- `1=Starting`
- `2=Active`
- `3=Paused`
- `4=DisableIn`
- `10=Failed`
- `11=Stopping`
- `12=Stopped`
- `13=Closing`
- `14=Finished`
- `15=TpStopped`
- `16=SlStopped`

## 3. Disclaimer

The `/tests` endpoints are reverse-engineered private endpoints and are not covered by public OpenAPI documentation. They may change or break without notice. Operational monitoring should treat unexpected 4xx responses from these endpoints as anomalies worth investigation.

## 4. Auth flow

- login step: `POST /accounts/login` with `{email, password}` where password is already SHA1-hashed
- if 2FA is required: `POST /accounts/twoFactor` with `{code}`
- final auth artifact: bearer token from response payload

Environment variables used:
- `GINAREA_EMAIL`
- `GINAREA_PASSWORD_SHA1`
- `GINAREA_TOTP_SECRET`

Token strategy in v1:
- token is stored in-memory only
- `GinAreaClient` retries one authenticated request after re-login on 401
- no token persistence or refresh cache is implemented in this foundation TZ

## 5. Rate limits

Documented constraint:
- more than one erroneous request per second can lead to an IP block for 2 minutes

Client strategy:
- minimum inter-request interval defaults to `1.1s`
- on HTTP 429, client sleeps `121s` and retries once
- on repeated 429, raises `GinAreaRateLimitError`
- on 5xx, retries with exponential backoff `1s`, `2s`, `4s`

## 6. Production bot guard

All mutating operations in this TZ go through `_assert_not_production()`:
- `BotsAPI.set_params()`
- `BacktestAPI.create_test()`

Guard source:
- reads `state/portfolio.json`
- accepts either:
  - `{"bots": [{"id": int, "active": bool}, ...]}`
  - or fallback `{"active_bot_ids": [int, ...]}`

Behavior:
- if file is missing or unreadable, guard logs a warning and uses an empty set
- this is intentional so unit tests and offline development do not fail hard
- if a bot id is in the production set, mutation raises `GinAreaProductionBotGuardError`
