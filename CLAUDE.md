# CLAUDE.md — MindRep

## Project Overview
MindRep is an exercise-as-precision-mental-health platform. Solo founder, 5-week MVP sprint to VC demo day. UK-first launch.

## Tech Stack
- **Mobile:** React Native + Expo (iOS-first) — `./mobile/`
- **Backend:** FastAPI (Python 3.11+) — `./backend/`
- **Database:** Supabase (PostgreSQL, EU region)
- **Hosting:** Railway (git-push deploy)
- **NLP:** Claude API (Anthropic) for mood classification
- **Anonymisation:** spaCy (en_core_web_sm) + regex — MUST run before any Claude API call
- **Wearables:** Apple HealthKit (react-native-health) + Oura REST API v2
- **Correlation:** pandas + scipy.stats + numpy (no ML in MVP)

## Critical Rules

### Data Protection (NEVER violate these)
1. Every journal entry MUST pass through `backend/app/services/anonymisation.py` before any external API call
2. Never send user IDs, names, emails, or any PII to the Claude API — only anonymised text
3. Biometric data (HRV, sleep, HR) NEVER leaves our infrastructure — no external API calls with this data
4. Check `ai_processing_consent` before calling Claude API for any user
5. All Supabase tables use row-level security (RLS) policies scoped to authenticated user

### Regulatory Language (user-facing copy only)
- Never use: diagnose, treat, cure, prescription (medical), therapy, clinical, symptoms, condition, disorder
- Always use: wellbeing insights, mood patterns, exercise recommendations, suggestions, wellness support
- Include disclaimer on health-adjacent screens: "MindRep is a wellness tool, not a medical device."

### Code Conventions
- Python: PEP 8, type hints on all functions, Pydantic models for request/response, async endpoints
- React Native: functional components + hooks, TypeScript, Expo Router for navigation
- API: RESTful, prefix `/api/v1/`, consistent `{ "data": ..., "error": null }` responses
- Tests: pytest for backend, adversarial PII tests for anonymisation pipeline are mandatory

## Commands
```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Mobile
cd mobile && npx expo start

# Tests
cd backend && pytest tests/ -v

# Database migrations
# Managed via Supabase dashboard or supabase CLI
```

## File Structure
```
mindrep/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── models/           # Pydantic schemas
│   │   ├── routers/          # API endpoints
│   │   ├── services/         # Business logic
│   │   │   ├── anonymisation.py  # PII stripping (spaCy + regex)
│   │   │   ├── mood_classifier.py # Claude API calls
│   │   │   ├── correlation.py     # pandas/scipy engine
│   │   │   ├── prescription.py    # Rule-based recommendations
│   │   │   └── oura.py            # Oura API client
│   │   └── db/
│   │       └── supabase.py
│   ├── tests/
│   └── requirements.txt
├── mobile/
│   ├── app/                  # Expo Router
│   │   ├── (auth)/
│   │   ├── (tabs)/
│   │   │   ├── checkin.tsx
│   │   │   ├── insights.tsx
│   │   │   ├── prescription.tsx
│   │   │   └── settings.tsx
│   │   └── onboarding/
│   ├── components/
│   ├── hooks/
│   │   ├── useHealthKit.ts
│   │   └── useMood.ts
│   ├── services/
│   │   └── api.ts
│   └── package.json
└── docs/
```

## Database Schema (Supabase)
Key tables: `users` (with consent booleans + timestamps), `mood_checkins` (mood_score 1-10, journal_text, ai_mood_label, ai_themes), `wearable_daily` (HRV, sleep, HR, steps per day per source), `exercise_sessions` (type, duration, intensity, source), `mood_prescriptions` (recommended exercise + reasoning), `user_correlations` (precomputed per-exercise-type correlations with r-values and p-values).

Full schema is in the Claude Project knowledge files and `docs/schema.sql`.

## Current Sprint Priority
Week-by-week priorities are in the product plan. When unsure what to build next, ask.
