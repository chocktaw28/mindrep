-- MindRep Database Schema
-- Run this in the Supabase SQL editor to set up all tables

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- USERS
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  date_of_birth DATE NOT NULL,
  timezone TEXT DEFAULT 'Europe/London',
  mood_data_consent BOOLEAN DEFAULT FALSE,
  mood_data_consent_at TIMESTAMPTZ,
  ai_processing_consent BOOLEAN DEFAULT FALSE,
  ai_processing_consent_at TIMESTAMPTZ,
  wearable_data_consent BOOLEAN DEFAULT FALSE,
  wearable_data_consent_at TIMESTAMPTZ,
  is_premium BOOLEAN DEFAULT FALSE,
  premium_since TIMESTAMPTZ,
  onboarding_completed BOOLEAN DEFAULT FALSE
);

-- MOOD CHECK-INS
CREATE TABLE mood_checkins (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  mood_score INTEGER NOT NULL CHECK (mood_score BETWEEN 1 AND 10),
  journal_text TEXT,
  manual_tags TEXT[],
  ai_mood_label TEXT,
  ai_intensity INTEGER CHECK (ai_intensity BETWEEN 1 AND 10),
  ai_themes TEXT[],
  ai_confidence FLOAT,
  ai_processed BOOLEAN DEFAULT FALSE
);

-- WEARABLE DAILY SUMMARIES
CREATE TABLE wearable_daily (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  date DATE NOT NULL,
  source TEXT NOT NULL,
  hrv_avg FLOAT,
  hrv_min FLOAT,
  hrv_max FLOAT,
  resting_hr FLOAT,
  sleep_duration_minutes INTEGER,
  sleep_deep_minutes INTEGER,
  sleep_rem_minutes INTEGER,
  sleep_score FLOAT,
  readiness_score FLOAT,
  steps INTEGER,
  active_calories FLOAT,
  UNIQUE(user_id, date, source)
);

-- EXERCISE SESSIONS
CREATE TABLE exercise_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  date DATE NOT NULL,
  exercise_type TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL,
  intensity TEXT CHECK (intensity IN ('low', 'moderate', 'vigorous')),
  avg_heart_rate FLOAT,
  calories FLOAT,
  source TEXT DEFAULT 'manual',
  notes TEXT
);

-- MOOD PRESCRIPTIONS
CREATE TABLE mood_prescriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  exercise_type TEXT NOT NULL,
  suggested_duration_minutes INTEGER,
  suggested_intensity TEXT,
  reasoning TEXT,
  confidence FLOAT,
  source TEXT DEFAULT 'rule_based',
  was_followed BOOLEAN,
  follow_up_mood_score INTEGER
);

-- USER CORRELATIONS (precomputed)
CREATE TABLE user_correlations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  computed_at TIMESTAMPTZ DEFAULT now(),
  exercise_type TEXT,
  mood_change_avg FLOAT,
  mood_change_pct FLOAT,
  correlation_r FLOAT,
  p_value FLOAT,
  sample_size INTEGER,
  lag_days INTEGER DEFAULT 1,
  insight_text TEXT
);

-- ROW-LEVEL SECURITY
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE mood_checkins ENABLE ROW LEVEL SECURITY;
ALTER TABLE wearable_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE exercise_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE mood_prescriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_correlations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own data" ON users FOR SELECT USING (auth.uid() = id);
CREATE POLICY "Users can update own data" ON users FOR UPDATE USING (auth.uid() = id);

CREATE POLICY "Users can view own checkins" ON mood_checkins FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can insert own checkins" ON mood_checkins FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users can delete own checkins" ON mood_checkins FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "Users can view own wearable data" ON wearable_daily FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can insert own wearable data" ON wearable_daily FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users can delete own wearable data" ON wearable_daily FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "Users can view own exercises" ON exercise_sessions FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can insert own exercises" ON exercise_sessions FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users can update own exercises" ON exercise_sessions FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "Users can delete own exercises" ON exercise_sessions FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "Users can view own prescriptions" ON mood_prescriptions FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can view own correlations" ON user_correlations FOR SELECT USING (auth.uid() = user_id);

-- INDEXES
CREATE INDEX idx_mood_checkins_user_date ON mood_checkins(user_id, created_at DESC);
CREATE INDEX idx_wearable_daily_user_date ON wearable_daily(user_id, date DESC);
CREATE INDEX idx_exercise_sessions_user_date ON exercise_sessions(user_id, date DESC);
CREATE INDEX idx_mood_prescriptions_user_date ON mood_prescriptions(user_id, created_at DESC);
CREATE INDEX idx_user_correlations_user ON user_correlations(user_id, exercise_type);
