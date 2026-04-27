# ChessCraft Documentation

Last updated: 2026-04-27  
Observed codebase state: Django web app + FastAPI engine service  
Observed versions in code:
- Website footer version: v1.3
- Game review algorithm version: 9
- Engine service title: V3 (Priority Queue)

## 1. Product Overview

ChessCraft is a chess improvement web platform that combines:
- Game import from Chess.com
- Position and game analysis powered by Stockfish
- Move-by-move review with classification and explanation
- Player insights dashboard based on analyzed games
- Basic play-vs-AI mode on the home page

Primary audience:
- Chess players who want practical review and trend tracking
- Users importing online games and reviewing mistakes

Core product modules:
- Authentication and account lifecycle (signup, OTP verification, login, reset password)
- Game synchronization from Chess.com archives
- Analysis hub and game review pipeline
- Insights dashboard (accuracy, trends, openings, move category distribution)
- Admin dashboard and error logging (server-side and client-side)

## 2. High-Level Architecture

### 2.1 System Components

1. Django monolith (web app)
- Handles templates, user flows, persistence, API endpoints, and business logic.
- Apps: main, authentication, user, analysis, insights.

2. Analysis engine adapter inside Django
- StockfishManager in analysis/engine.py.
- Supports remote engine API mode and local Stockfish binary fallback mode.

3. Remote engine microservice (optional but primary in production)
- FastAPI app in engine_service/app.py.
- Exposes /analyze, /analyze_batch, /health.
- Uses priority queue for manual analysis vs batch requests.

4. Data stores
- PostgreSQL in production (default)
- SQLite fallback in local/offline setup

5. Frontend
- Django templates + static CSS/JS
- chessboard.js/chess.js for board UI interactions
- Chart.js for graphs

### 2.2 Runtime Request Flow (Typical)

A. Game import flow
1. User enters Chess.com username and date range on /user/game/.
2. Django fetches Chess.com archive URLs and monthly game data.
3. Games are normalized and bulk inserted with dedupe safeguards.
4. User sees imported game cards and can open game review.

B. Full game review flow
1. Frontend opens /analysis/game/<game_id>/ and calls /analysis/api/review/start/.
2. Django parses PGN and builds FEN list for all plies.
3. Django sends one batch request to engine (remote or local fallback).
4. Move classification + per-side accuracy are computed.
5. SavedAnalysis and MoveAnalysis rows are stored, Game.accuracy/is_analyzed updated.
6. Payload is returned to frontend and rendered as interactive review.

C. Insights flow
1. Frontend page /insights/ calls summary/trend/openings and then analytical APIs.
2. APIs aggregate data from latest SavedAnalysis per game and Game records.
3. Charts and tips are rendered client-side.

## 3. Project Structure and Responsibilities

Top-level key directories/files:
- ChessCraft/: project config (settings, urls, wsgi, asgi, shared utils)
- main/: public pages, contact form, play-vs-AI endpoint, error logging
- authentication/: registration, OTP verification, login/reset flows
- user/: custom user model, imported games, profile and data cleanup actions
- analysis/: engine adapter, review algorithm, analysis endpoints, analysis models
- insights/: aggregated analytics APIs and dashboard page
- engine_service/: standalone FastAPI Stockfish service
- templates/: shared templates and custom admin dashboard
- static/: CSS/JS assets
- deployment.txt: deployment guide
- local.env.template, production.env.template: environment templates

## 4. Technology Stack

Backend:
- Django 6.0.x
- python-chess/chess
- requests
- psycopg2-binary
- django-environ

Frontend:
- Django templates
- Bootstrap + Bootstrap Icons
- chessboard.js
- chess.js
- Chart.js

Engine service:
- FastAPI
- Uvicorn
- python-chess + Stockfish

Infrastructure patterns:
- WhiteNoise for static serving
- Gunicorn + Nginx deployment model (documented in deployment.txt)

## 5. Configuration Reference

### 5.1 Core Environment Variables

Security and runtime:
- SECRET_KEY
- DEBUG
- ALLOWED_HOSTS
- CSRF_TRUSTED_ORIGINS

Database:
- DB_ENGINE (postgres or sqlite)
- DB_NAME
- DB_USER
- DB_PASSWORD
- DB_HOST
- DB_PORT
- DB_CONNECT_TIMEOUT

Analysis engine:
- ANALYSIS_ENGINE_MODE (remote/local)
- ANALYSIS_ENGINE_URL
- ANALYSIS_ENGINE_TOKEN
- ANALYSIS_ENGINE_DEPTH
- ANALYSIS_ENGINE_TIME
- ANALYSIS_ENGINE_THREADS
- ANALYSIS_ENGINE_HASH
- ANALYSIS_GAME_REVIEW_DEPTH
- STOCKFISH_PATH
- ANALYSIS_ENGINE_TIMEOUT (read by code if set)

Site/email:
- SITE_ID
- SITE_URL
- EMAIL_HOST_USER
- EMAIL_HOST_PASSWORD
- DEFAULT_FROM_EMAIL

### 5.2 Noted Config Behavior

- The settings file defines ANALYSIS_GAME_REVIEW_DEPTH from env, but later hard-overrides it to 16.
- Local and production templates default to remote engine mode.
- local.env.template includes T_TIMEOUT, which is not currently consumed by code.

## 6. URL and Endpoint Reference

### 6.1 Top-Level Routing

Mounted routes:
- / -> main.urls
- /admin-panel/ -> Django admin
- /auth/ -> authentication.urls
- /user/ -> user.urls
- /analysis/ -> analysis.urls
- /insights/ -> insights.urls

Error handlers:
- 404 -> main.views.error_404
- 500 -> main.views.error_500

### 6.2 Main App

Pages:
- GET / -> Home
- GET /about/ -> About
- GET /contact/ -> Contact form page

APIs:
- POST /api/play-vs-ai/
  - Input: fen, elo
  - Output: best_move, evaluation
  - Uses StockfishManager with elo-limited analysis; adds randomization for very low Elo

- POST /api/client-error/
  - Input: browser-side JS error payload
  - Output: status ok
  - Persists client errors to ErrorLog (best effort)

### 6.3 Authentication App

- GET/POST /auth/signup/
- GET/POST /auth/verify/<pending_id>/
- GET /auth/resend-signup/<pending_id>/
- GET/POST /auth/login/
- GET /auth/logout/
- GET/POST /auth/forgot-password/
- GET/POST /auth/forgot-verify/<user_id>/
- GET/POST /auth/reset-password/<user_id>/
- GET /auth/resend/<user_id>/

### 6.4 User App

- GET/POST /user/game/
  - POST: sync Chess.com games
  - GET: paginated game library with username/opening filters

- GET/POST /user/profile/
  - delete all games + analyses
  - delete games + analyses for a selected Chess.com username

- POST /user/delete-account/
  - password confirmation required

### 6.5 Analysis App

Pages:
- GET /analysis/ -> analysis hub
- GET /analysis/paste-pgn/
- GET /analysis/setup-position/
- GET /analysis/new-game/
- GET /analysis/game/<game_id>/ -> review UI

APIs:
- POST /analysis/api/analyze/
  - single-position analysis (supports multipv up to 3)

- POST /analysis/api/variation/
  - analyze candidate move from a position

- POST /analysis/api/review/start/
  - full game review generation and persistence
  - returns cached payload if algorithm version matches

- GET /analysis/api/review/latest/<game_id>/
  - fetch latest saved review

- POST /analysis/api/analyze-period/
  - analyze up to 20 (or 10 when busy) non-bullet games
  - period: week or month

- GET /analysis/health/
  - proxies engine health

### 6.6 Insights App

- GET /insights/ -> dashboard page
- GET /insights/api/summary/?username=<name>
- GET /insights/api/trend/?username=<name>
- GET /insights/api/move-breakdown/?username=<name>
- GET /insights/api/openings/?username=<name>&color=white|black
- GET /insights/api/phases/?username=<name>

Insights intentionally exclude bullet-like time controls:
- 60, 60+1, 60+2, 30, 120, 120+1

## 7. Data Model Documentation

### 7.1 user.User

Custom auth model extending AbstractUser with:
- chess_username

### 7.2 user.Game

Stores synchronized game records.
Key fields:
- user (FK)
- chess_username_at_time
- game_id (Chess.com UUID)
- date_played
- players, ratings, result, time_control
- opening, pgn
- accuracy, is_analyzed

Constraint:
- UniqueConstraint(user, game_id)

### 7.3 analysis.SavedAnalysis

Stores aggregate review output and payload.
Key fields:
- user (FK), game (FK)
- pgn_data
- full_payload (JSON)
- white/black accuracy and estimated ratings
- phase accuracies by side
- category counts
- opening, eco_code, result_reason

### 7.4 analysis.MoveAnalysis

Stores per-move snapshots for each SavedAnalysis.
Fields:
- analysis (FK)
- move_number, notation, fen, evaluation, classification, explanation

### 7.5 authentication.PendingRegistration and UserOTP

Temporary OTP models for signup and password reset.
- 6-digit OTP
- expiry window (5 minutes)

### 7.6 main.ContactMessage and ErrorLog

ContactMessage:
- user messages from contact form

ErrorLog:
- captures server/client errors, metadata, stack traces, user context

## 8. Analysis Engine: Current Version

## 8.1 Current Engine Version Snapshot

Engine architecture currently combines:

1. Django-side adapter (StockfishManager)
- Mode selection: remote first when configured, else local fallback
- Supports single, multipv, and batch analysis APIs
- Normalizes output fields (cp, eval, best move, pv, depth, mate)

2. Remote service (engine_service V3)
- FastAPI service with priority queue
- Endpoints: /analyze, /analyze_batch, /health
- Single async worker loop consuming queued tasks
- High priority for manual requests, normal for batch

3. Review algorithm (version 9)
- Batches all game FENs in one review request
- Computes classification categories:
  - brilliant, great, best, excellent, good, book, inaccuracy, miss, mistake, blunder
- Uses win-percent based grading and mate-distance smoothing
- Persists full payload for replay and caching by algo version

### 8.2 Current Strengths (Pros)

- Flexible deployment model: local-only, remote-only, or fallback behavior.
- Priority-aware queueing allows user-triggered analysis to outrank background batch jobs.
- Batch review is implemented end-to-end, reducing per-move HTTP overhead.
- Full payload persistence avoids repeated recomputation for unchanged algorithm versions.
- Health endpoint integrated with frontend/server behavior for adaptive batch limits.
- Move classification logic is richer than basic centipawn thresholds.
- Error handling wrappers exist in API layers, with DB-backed error logging.

### 8.3 Current Weaknesses (Cons)

Performance and throughput:
- Remote service runs a single worker loop, limiting concurrency under load.
- Worker opens and closes a Stockfish process per task, adding overhead.
- /analyze_batch is decomposed into many queue tasks, still serialized by one worker.
- Full review remains synchronous HTTP from frontend perspective; long jobs can feel slow.

Algorithm quality and consistency:
- Book detection uses local heuristics only, which can misclassify opening theory.
- Classification for great/brilliant does not use true multi-PV gap analysis in review path.
- Some insight calculations rely on full_payload split counts; older payloads can degrade quality.

Operational and reliability concerns:
- Bare except blocks in multiple areas can hide root causes.
- Secrets/tokens appear in templates/scripts and should be rotated/removed from repo.
- No explicit rate limiting/backpressure contract at Django API boundary.

Config and maintainability issues:
- Review depth env can be overridden unintentionally by hardcoded setting.
- Date range mapping in game import has an inconsistency:
  - month option in UI maps to 60 days in utility logic.
- Test files are mostly placeholders, increasing regression risk.

## 9. Recommended Next Version (Performance-Focused Upgrade)

Suggested target: Engine Service V4 + Review Algorithm V10

### 9.1 V4 Engine Service Goals

Target outcomes:
- Lower p95 latency for single-position analysis
- Higher throughput during concurrent reviews
- Better queue fairness and observability

Recommended changes:

1. Multi-worker execution
- Run a pool of workers (for example, min(cpu_count-1, 4) initially).
- Each worker owns a persistent Stockfish instance.

2. Persistent engine lifecycle
- Do not spawn/quit Stockfish per task.
- Warm engine once per worker and reuse across tasks.

3. True batch optimization
- Keep /analyze_batch as one request, but process positions efficiently with worker pool.
- Consider chunked batch execution for very long games.

4. Caching
- Add cache for key (fen, depth, multipv, elo, engine_version).
- Use Redis (preferred) with short TTL for interactive calls and longer TTL for review calls.

5. Async job protocol for full review
- Introduce job-based endpoints:
  - POST /analysis/api/review/jobs
  - GET /analysis/api/review/jobs/<id>
  - GET /analysis/api/review/jobs/<id>/result
- Frontend can poll progress and avoid long blocking request windows.

6. Better health/metrics
- Expose queue depth, worker utilization, average task times, timeout/error rates.
- Export Prometheus-style metrics if possible.

7. Security hardening
- Rotate engine token.
- Remove hardcoded credentials from scripts and templates.
- Restrict service network ingress to trusted app hosts.

### 9.2 V10 Review Algorithm Goals

1. Improve move-quality classification fidelity
- Use true multi-PV deltas (best vs second-best vs played line) for great/brilliant detection.
- Add tactical opportunity detection using PV shifts instead of cp-only heuristics.

2. Opening identification quality
- Replace heuristic book detection with local ECO database or polyglot book lookup.
- Persist opening confidence/source metadata.

3. Adaptive depth/time policy
- Dynamically scale depth based on position complexity and game phase.
- Use lower depth for quiet forced recaptures and higher depth for tactical nodes.

4. Data model versioning
- Persist analysis_engine_version and review_algo_version per SavedAnalysis.
- Allow selective re-analysis only when versions changed materially.

### 9.3 Database and Query Improvements

Add/verify useful indexes:
- Game(user, chess_username_at_time, date_played, is_analyzed)
- SavedAnalysis(user, game, id)
- ErrorLog(created_at, kind)

Model evolution suggestions:
- Add explicit per-side count fields if insights should not depend on full_payload structure.
- Add last_analyzed_at and analysis_duration_ms for observability and tuning.

### 9.4 Frontend and UX Improvements

- Replace alert() usage in insights with inline toasts/progress status.
- For long reviews, show queue position and estimated remaining time.
- Add retry with exponential backoff on analysis API calls.
- Persist user-selected filters and dashboard tabs in local storage.

## 10. Upgrade Roadmap (Practical Sequence)

Phase 0: Quick wins (1-2 days)
- Remove hardcoded secrets from repository files.
- Fix month/60-day mapping inconsistency in import utility.
- Fix review depth config override behavior.
- Add structured logging in engine and Django analysis endpoints.

Phase 1: Throughput upgrade (1 week)
- Implement persistent multi-worker engine service.
- Add improved /health payload and queue metrics.
- Add benchmark script for representative loads.

Phase 2: Async reviews + caching (1-2 weeks)
- Move full review generation to job-based API.
- Add FEN cache and deduplicated repeated computations.

Phase 3: Algorithm V10 (1-2 weeks)
- Introduce multipv-aware classification refinements.
- Add robust opening/book mapping source.
- Backfill re-analysis for recent important games.

Phase 4: QA and rollout
- Canary deploy with feature flag for V4/V10.
- Compare p95 latency, timeout rate, and user completion metrics.
- Rollback switch retained for safety.

## 11. Observability and Operations

Current observability assets:
- ErrorLog model + middleware/API decorator logging
- Client JS error reporter posting to /api/client-error/
- Engine health endpoint with queue/active task counters
- Admin dashboard metrics for users, fetched games, analyses

Recommended additions:
- Correlation IDs per request/job
- Structured logs with event names and timings
- Daily error digest and alert thresholds
- Separate engine and web dashboards (latency, queue, error rates)

## 12. Security and Compliance Notes

Immediate priorities:
- Rotate any exposed DB passwords and engine tokens.
- Remove credentials from engine_service/setup_remote.sh and env templates.
- Enforce least-privilege DB user grants.
- Restrict public access to engine and database ports.

General hardening:
- Add brute-force protections on auth endpoints.
- Add API rate limiting for analysis endpoints.
- Validate and sanitize all user-provided PGN/FEN inputs (already partially done).

## 13. Testing Strategy (Needed)

Current status:
- Test files exist in apps but are mostly placeholders.

Minimum high-value test suite to add:
- Unit tests for classification and accuracy functions in analysis/engine.py
- Integration tests for review API and saved payload caching behavior
- Import pipeline tests for dedupe, date filtering, and result normalization
- Insights API contract tests for summary/trend/openings/phase outputs
- Engine adapter tests (remote success, timeout, fallback, malformed payload)

Performance tests:
- Single-position latency at depth 16/20
- Full game review timing for typical 40/80 ply games
- Concurrent mixed workload (manual + batch)

## 14. Developer Setup (Quick Reference)

Local setup summary:
1. Create and activate venv.
2. Install dependencies from requirements.txt.
3. Copy local.env.template to .env and fill values.
4. Run migrations.
5. Run Django dev server.

Optional remote engine service setup:
- Deploy engine_service app with Stockfish installed.
- Set ANALYSIS_ENGINE_MODE=remote and engine URL/token in Django env.

Production setup reference:
- See deployment.txt for Gunicorn + Nginx + Certbot flow.

## 15. Known Technical Debt and Inconsistencies

1. Review depth variable is set twice in settings (env then constant override).
2. Date range mapping inconsistency between user form values and fetch utility logic.
3. Hardcoded secrets in repo artifacts (must rotate/remove).
4. Sparse automated tests.
5. Some legacy template/content strings reference ChessWeb instead of ChessCraft.
6. Duplicate package naming in dependencies (both chess and python-chess listed).

## 16. Final Summary

ChessCraft already has a solid architecture for practical chess analysis with real user value:
- reliable data ingestion,
- meaningful review outputs,
- and a useful insights dashboard.

The main constraint now is analysis throughput and operational resilience under load. Moving from Engine V3 to a multi-worker, persistent-engine V4 architecture and upgrading review logic to V10 (multipv-aware) will deliver the biggest gains in performance, consistency, and user experience.
