# Markets and KYC Workflow Review

## Canonical Fan KYC

The six-stage Fan flow remains Get Started, Personal Details, Identity Document, Live Selfie, Review & Submit, and Verification Status. Submission is multipart data sent to `POST /api/v1/fans/kyc/`; status comes from canonical `KYCVerification`, not `User.is_verified`. The UI represents NOT_STARTED, PENDING, PROCESSING, REVIEW, RETRY_REQUIRED, VERIFIED, REJECTED, and EXPIRED, including attempts, configured maximum attempts, submission/decision timestamps, safe reasons, and any separate Markets eligibility blocker.

Every automated or manual canonical decision synchronizes `MarketParticipantCompliance` through `KYCMarketComplianceSyncService`. The Compliance workspace reads real canonical records and keeps `manage_compliance` authorization. It exposes masked document data, extracted identity/check/risk data where present, timestamps, and real Verify/Reject actions. No unsupported Request Retry action was invented.

## Local-development KYC bypass

`POST /api/v1/fans/kyc/dev-bypass/` acts only on the authenticated Fan and accepts no target user. It is unavailable unless `DEBUG=True`, `DEV_KYC_BYPASS_ENABLED=True`, authentication succeeds, and the email ends in `@leagueos.test`. Defaults are false in `.env.example`; the frontend additionally requires a development build and `VITE_DEV_KYC_BYPASS=true`.

The bypass writes canonical VERIFIED state with explicit `verification_source=DEVELOPMENT_BYPASS`, creates an audit event, and invokes the same canonical Markets compliance sync. It creates no attempt, provider reference, OCR/check row, liveness score, face-match score, or document evidence. The Fan UI says “Verified for local development testing” and explicitly states that external checks were not claimed.

## Result verification lifecycle

The server-backed queue includes CLOSED, RESOLVED, and VOIDED markets and derives Awaiting Result, Dispute Window, Disputed, Ready to Resolve, Ready to Settle, Settled, and Voided / Refunded from persisted backend facts. CLOSED is not presented as cancelled.

A result verifier publishes a provisional binary YES/NO outcome through `MarketProvisionalResultService`, with required notes and evidence. Publication does not resolve or settle. The real configured deadline controls the dispute window; open disputes block financial finalization. Existing Confirm, Correct, Void, and Extend Review decisions retain their notes/evidence and independent-actor rules.

Final YES/NO resolution and settlement remain separate actions. Resolution sets RESOLVED and the canonical winning outcome but does not claim payouts. Settlement calls the real endpoint and `MarketSettlementService`, which enforces the resolved winner, closed dispute window, no open disputes, no outstanding open/partial commitments, no reserved quantities, and idempotency. Wallet credits continue exclusively through `WalletService` and immutable ledger references. Void uses the authoritative refund workflow, has no winner, and cannot also receive normal settlement.

## Local-development dispute accelerator

The development action creates an immutable `MarketResultDevelopmentAcceleration` audit marker; it does not rewrite provisional evidence/deadlines, delete disputes, resolve, settle, or fabricate a result. It is available only when `DEBUG=True`, `DEV_RESULT_ACCELERATOR_ENABLED=True`, the actor has result-verification permission, both actor and market creator are synthetic `@leagueos.test` accounts, and a provisional result exists. The frontend additionally requires a development build and `VITE_DEV_RESULT_ACCELERATOR=true`.

## UGX 10,000 payout semantics

`Market.face_value_ugx` defaults to UGX 10,000 for new markets. Normalized outcome price remains a probability/value ratio: at 0.60000, one displayed full UGX 10,000 share costs about UGX 6,000. Backend quantity is settlement-value units, so that displayed full share is 10,000 backend units. Existing payout-per-unit accounting therefore produces UGX 10,000 gross for a winning full share and UGX 0 for a losing full share; it must not multiply the already-scaled quantity by face value again. A dedicated settlement test proves UGX 6,000 cost, UGX 10,000 gross payout, and UGX 4,000 pre-fee realized profit.

## Validation results (2026-08-14)

- KYC bypass, canonical sync, and result-state focused tests: 19 passed.
- Result accelerator security tests: 4 passed.
- Combined KYC/result/dispute/settlement/void/opening-pricing focused suite: 127 passed, 33 subtests passed.
- Full Markets suite: attempted on isolated SQLite but exceeded the 604-second command timeout without producing a final count; no result is claimed.
- Frontend focused service tests: 10 passed.
- Full frontend suite: 209 passed in 33 files.
- Frontend ESLint: passed.
- Frontend production build: passed, with existing asset/chunk warnings.
- Django check: passed.
- `makemigrations --check --dry-run`: passed; no uncommitted model drift.
- `migrate --check`: passed against the isolated SQLite configuration, with the existing SQLite null-distinct constraint warning.
- Black check: passed (587 files unchanged).
- Ruff initially identified a missing `__str__` on the new audit model; corrected and rerun in final validation.
- `git diff --check`: passed with only the existing Windows LF/CRLF notice.

No remote, staging, Neon, or Render write was made. No commit, push, merge, or deployment was performed.

## Remaining gaps / browser prerequisites

- Browser acceptance still requires locally running backend, frontend, PostgreSQL, and Redis; migrations 0024, 0025, and `kyc.0004`; seeded `compliance.local@leagueos.test`, `results.local@leagueos.test`, and `market.ops.local@leagueos.test`; synthetic CLOSED market data; and explicit local-only flags enabled in untracked worktree environment files.
- Back-side identity document storage is not supported by the canonical KYC attempt model.
- Private document/selfie viewing still needs a complete signed-token download flow.
- No safe admin Request Retry endpoint exists, so the UI does not invent one.
- Initial liquidity remains deferred until a collateralized, auditable bootstrap primitive exists.
