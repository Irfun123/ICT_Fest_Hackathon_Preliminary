# Bug Report

## 1. Offset datetimes were not converted to UTC

- **Files/lines:** `app/timeutils.py`, line 13
- **Bug:** `parse_input_datetime()` previously removed timezone information with `replace(tzinfo=None)`. For inputs like `2026-08-01T10:00:00+06:00`, this stored `10:00` instead of converting it to the correct UTC instant.
- **Why incorrect:** Rule 1 says API datetimes with UTC offsets must be converted to UTC before storage or comparison.
- **Fix:** Changed offset handling to `dt.astimezone(timezone.utc).replace(tzinfo=None)`.

## 2. Access tokens expired after 15 hours instead of 900 seconds

- **Files/lines:** `app/auth.py`, line 53
- **Bug:** `create_access_token()` used `timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES * 60)`, making the default 15-minute setting become 900 minutes.
- **Why incorrect:** Rule 8 requires access tokens to expire in exactly 900 seconds.
- **Fix:** Changed the lifetime calculation to `timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)`.

## 3. Logout blacklist checked the wrong token claim

- **Files/lines:** `app/auth.py`, lines 88-90 and 119-121
- **Bug:** Logout stored token `jti`, but authenticated requests checked `sub` against the revoked-token set. A logged-out access token could still be reused.
- **Why incorrect:** Rule 8 says logout immediately invalidates the presented access token.
- **Fix:** Revoked and checked access tokens by `jti`, protected by a lock.

## 4. Refresh tokens were reusable

- **Files/lines:** `app/auth.py`, lines 26-27 and 103-108; `app/routers/auth.py`, lines 83-87
- **Bug:** `POST /auth/refresh` decoded refresh tokens and issued new tokens without invalidating the presented refresh token.
- **Why incorrect:** Rule 8 says refresh tokens are single-use; reuse must return 401.
- **Fix:** Added an in-memory used-refresh-token set with an atomic `use_refresh_token_once()` check, and call it during refresh.

## 5. Duplicate registration returned an existing user instead of an error

- **Files/lines:** `app/routers/auth.py`, lines 37-43
- **Bug:** Registering the same username in the same org returned the existing user payload.
- **Why incorrect:** Rule 15 requires duplicate username within an org to return `409 USERNAME_TAKEN`.
- **Fix:** Changed duplicate username handling to raise `AppError(409, "USERNAME_TAKEN", ...)`.

## 6. Registration had a check/create race

- **Files/lines:** `app/routers/auth.py`, lines 23 and 28-53
- **Bug:** Concurrent registration requests could both observe missing org/user state before either committed.
- **Why incorrect:** Rule 15 defines deterministic org/admin/member and duplicate-username behavior.
- **Fix:** Added a narrow registration lock around org lookup/create and user lookup/create.

## 7. Back-to-back bookings were treated as conflicts

- **Files/lines:** `app/routers/bookings.py`, line 52
- **Bug:** `_has_conflict()` used inclusive comparisons: `existing.start <= new.end` and `new.start <= existing.end`.
- **Why incorrect:** Rule 3 defines overlap with strict comparisons and explicitly allows back-to-back bookings.
- **Fix:** Changed the overlap test to `existing.start < new.end and new.start < existing.end`.

## 8. Booking start time allowed a five-minute grace window

- **Files/lines:** `app/routers/bookings.py`, line 88
- **Bug:** `create_booking()` allowed starts up to five minutes in the past.
- **Why incorrect:** Rule 2 requires `start_time` to be strictly in the future with no grace window.
- **Fix:** Changed validation to reject `start <= now`.

## 9. Booking duration did not enforce the minimum one hour

- **Files/lines:** `app/routers/bookings.py`, line 95
- **Bug:** Duration validation rejected non-whole-hour and over-8-hour bookings, but did not reject zero or negative whole-hour durations.
- **Why incorrect:** Rule 2 requires whole-hour duration, minimum 1 hour, maximum 8 hours, and end strictly after start.
- **Fix:** Added `duration_hours < MIN_DURATION_HOURS` to the invalid-window check.

## 10. Booking conflict and quota checks were not concurrency-safe

- **Files/lines:** `app/routers/bookings.py`, lines 26 and 98-125
- **Bug:** Conflict/quota checks happened before insert without a shared critical section, so concurrent requests could pass checks and then both create bookings.
- **Why incorrect:** Rules 3 and 4 require no double-booking and quota enforcement under concurrent requests.
- **Fix:** Added a narrow booking lock around room lookup, conflict check, quota check, booking creation, commit, and cache/stat updates.

## 11. Booking creation did not invalidate usage reports

- **Files/lines:** `app/routers/bookings.py`, line 125
- **Bug:** Creating a booking invalidated availability but not usage report cache.
- **Why incorrect:** Rule 12 requires usage reports to reflect current state immediately.
- **Fix:** Invalidated report cache for the user org after successful booking creation.

## 12. Booking list pagination skipped the first page and ignored limit

- **Files/lines:** `app/routers/bookings.py`, lines 141-143
- **Bug:** `GET /bookings` sorted descending, used `offset(page * limit)`, and hardcoded `.limit(10)`.
- **Why incorrect:** Rule 11 requires ascending order by `start_time`, ties by ascending `id`, offset `(page - 1) * limit`, and caller-provided `limit`.
- **Fix:** Changed ordering to ascending, offset to `(page - 1) * limit`, and limit to `limit`.

## 13. Members could read other members' bookings in the same org

- **Files/lines:** `app/routers/bookings.py`, lines 156-168
- **Bug:** `GET /bookings/{id}` scoped by org but did not reject another member's booking.
- **Why incorrect:** Rule 10 says members may read only their own bookings; another member's booking id must behave as `404 BOOKING_NOT_FOUND`.
- **Fix:** Added a non-admin ownership check that raises `BOOKING_NOT_FOUND`.

## 14. Booking detail returned created_at as start_time

- **Files/lines:** `app/routers/bookings.py`, line 170 removed
- **Bug:** `get_booking()` serialized the booking correctly, then overwrote `start_time` with `booking.created_at`.
- **Why incorrect:** API contract requires booking `start_time` to be the booked interval start.
- **Fix:** Removed the incorrect overwrite.

## 15. Cancellation refund tiers were wrong

- **Files/lines:** `app/routers/bookings.py`, lines 204-211
- **Bug:** Exactly 48 hours did not qualify for 100%, and cancellations under 24 hours returned 50%.
- **Why incorrect:** Rule 6 requires `notice >= 48h` => 100%, `24h <= notice < 48h` => 50%, and `< 24h` => 0%.
- **Fix:** Compared notice directly with `timedelta(hours=48)` and set the final else branch to 0%.

## 16. Refund rounding and stored refund amount could differ from response

- **Files/lines:** `app/routers/bookings.py`, lines 213-220; `app/services/refunds.py`, lines 14-21
- **Bug:** The response used Python `round()`, while `log_refund()` separately calculated and committed a truncated amount from a percentage. This could disagree for half-cent cases like 50% of 1001.
- **Why incorrect:** Rule 6 requires half-cents to round up and the cancel response amount to equal the amount stored in `RefundLog`.
- **Fix:** Calculated refund cents once with integer half-up rounding, changed `log_refund()` to accept `amount_cents` directly, and committed the booking status/refund entry together once.

## 17. Concurrent cancellation could create multiple refund logs

- **Files/lines:** `app/routers/bookings.py`, lines 189-224; `app/services/refunds.py`, lines 14-21
- **Bug:** The old flow checked status, committed the refund, then later marked the booking cancelled. Concurrent requests could both see confirmed state and create more than one refund.
- **Why incorrect:** Rule 6 requires a cancelled booking to have exactly one `RefundLog` and cancellation to hold under concurrent requests.
- **Fix:** Put cancellation status check, refund creation, status update, and commit inside the booking lock; removed commit/refresh from `log_refund()`.

## 18. Cancellation did not invalidate room availability

- **Files/lines:** `app/routers/bookings.py`, line 224
- **Bug:** Cancelling a booking invalidated reports but not the room availability cache.
- **Why incorrect:** Rule 13 requires availability to reflect current confirmed bookings immediately.
- **Fix:** Invalidated availability for the booking room and UTC start date after cancellation.

## 19. Usage report cached stale results and mishandled ISO datetime bounds

- **Files/lines:** `app/routers/admin.py`, lines 18-25 and 35-64
- **Bug:** `GET /admin/usage-report` used cached responses and only parsed date strings into whole-day ranges. It could return stale data and did not correctly support ISO datetime query values.
- **Why incorrect:** Rule 12 requires current state immediately and confirmed bookings starting in inclusive UTC range `[from, to]`.
- **Fix:** Removed report caching from the endpoint and added `_parse_report_bound()` to handle date-only and ISO datetime bounds with inclusive end behavior.

## 20. Export could leak bookings from another organization

- **Files/lines:** `app/routers/admin.py`, lines 74-78; `app/services/export.py`, lines 22-41
- **Bug:** When `include_all=true` and `room_id` was provided, export used a raw room-id query without org scoping.
- **Why incorrect:** Rule 9 requires users, including admins, to only access data from their own organization; cross-org resource IDs behave as non-existent.
- **Fix:** Removed the raw export query, routed all export reads through org-scoped `_fetch_scoped()`, and added a same-org room check in the admin route.

## 21. Room stats could drift from actual confirmed bookings

- **Files/lines:** `app/routers/rooms.py`, lines 104-119
- **Bug:** `GET /rooms/{id}/stats` previously returned values from an in-memory incremental stats store, which could drift after concurrency or process restart.
- **Why incorrect:** Rule 14 requires stats to always equal the values derivable from confirmed bookings themselves.
- **Fix:** Changed `room_stats()` to aggregate confirmed bookings directly from the database.

## 22. Room creation did not invalidate usage reports

- **Files/lines:** `app/routers/rooms.py`, line 56
- **Bug:** Creating a new room did not invalidate cached usage reports.
- **Why incorrect:** Rule 12 requires reports to include rooms with zero bookings and reflect current state immediately.
- **Fix:** Invalidated report cache for the admin org after room creation.

## 23. Rate limiting was not concurrency-safe

- **Files/lines:** `app/services/ratelimit.py`, lines 3, 11, and 20-29
- **Bug:** The in-memory per-user bucket was read, trimmed, appended, and written without synchronization.
- **Why incorrect:** Rule 5 requires the 20 requests per rolling 60 seconds limit to hold under concurrent requests.
- **Fix:** Added a shared lock around the entire rate-limit update and check.

## 24. Reference code generation was not concurrency-safe

- **Files/lines:** `app/services/reference.py`, lines 7, 10, and 19-24
- **Bug:** Concurrent calls could read the same counter value before incrementing it, producing duplicate reference codes.
- **Why incorrect:** Rule 7 requires every booking reference code to be unique, including under concurrent creation.
- **Fix:** Added a shared lock around counter read, formatting pause, increment, and return.

## 25. Docker build context included local unreadable cache/venv artifacts

- **Files/lines:** `.dockerignore`, lines 4-6
- **Bug:** `docker compose up --build` failed while uploading context because local cache/venv artifacts such as `.pytest_cache/` were not ignored.
- **Why incorrect:** The challenge expects the project to build and run with Docker.
- **Fix:** Added `.pytest_cache/`, `.codex-verify-venv/`, and `.venv-1/` to `.dockerignore`.

## 26. Artificial sleeps slowed concurrent request paths

- **Files/lines:** `app/routers/bookings.py`, lines 29-38; `app/services/ratelimit.py`, lines 13-14; `app/services/reference.py`, lines 12-14
- **Bug:** Conflict checking, quota auditing, cancellation settlement, rate limiting, and reference-code generation included artificial `time.sleep()` delays.
- **Why incorrect:** Rule 16 requires the service to stay live under concurrent valid requests; artificial sleeps in locked or high-traffic paths increase latency and concurrency risk.
- **Fix:** Removed the sleep calls and made those helper functions no-ops.

## 27. Availability endpoint could return cached stale data

- **Files/lines:** `app/routers/rooms.py`, lines 66-93
- **Bug:** `GET /rooms/{id}/availability` read from and wrote to an in-memory availability cache.
- **Why incorrect:** Rule 13 requires availability to reflect current confirmed bookings immediately.
- **Fix:** Removed the availability cache read/write from the endpoint so it always queries confirmed bookings from the database.

## 28. Notification side effects could deadlock

- **Files/lines:** `app/services/notifications.py`, lines 10-32
- **Bug:** Booking creation acquired the email lock before the audit lock, while cancellation acquired the audit lock before the email lock. Concurrent create and cancel requests could each hold one lock and wait forever for the other.
- **Why incorrect:** Rule 16 requires the service to remain live; no combination of concurrent valid requests may hang the service.
- **Fix:** Removed the simulated blocking notification locks and sleeps. Notification hooks now return immediately.

## 29. Stats bookkeeping still slept in booking paths

- **Files/lines:** `app/services/stats.py`, lines 6-18; `app/routers/bookings.py`, lines 119 and 218
- **Bug:** The in-memory stats helper still slept during booking creation and cancellation, including while the booking lock was held.
- **Why incorrect:** Rule 16 requires liveness under concurrent activity; artificial sleeps in locked request paths reduce throughput and increase timeout risk.
- **Fix:** Removed the remaining artificial stats delay.

## 30. Malformed booking datetimes could return a server error

- **Files/lines:** `app/routers/bookings.py`, lines 80-84
- **Bug:** Invalid datetime strings raised `ValueError` from `datetime.fromisoformat()` and could escape as a 500 response.
- **Why incorrect:** Booking-window problems must use the contract error shape rather than an internal server error.
- **Fix:** Catch invalid datetime parsing during booking creation and return `400 INVALID_BOOKING_WINDOW`.
