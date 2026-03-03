import { useState } from 'react';
import { api } from '@/services/api';

export type MoodTrendPoint = {
  date: string;
  mood_score: number;
};

export type CorrelationSummary = {
  exercise_type: string;
  mood_change_pct: number;
  p_value: number;
  sample_size: number;
  insight_text: string;
};

export type WeeklyInsightsResponse = {
  mood_trend: MoodTrendPoint[];
  top_correlations: CorrelationSummary[];
  exercise_summary: Record<string, number>;
  week_start: string;
  week_end: string;
};

type Status = 'idle' | 'loading' | 'success' | 'error';

export function useInsights() {
  const [status, setStatus] = useState<Status>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [data, setData] = useState<WeeklyInsightsResponse | null>(null);

  async function fetch() {
    setStatus('loading');
    setErrorMessage(null);
    try {
      const result = await api.get<WeeklyInsightsResponse>('/insights/weekly');
      setData(result);
      setStatus('success');
    } catch (e: unknown) {
      setErrorMessage(e instanceof Error ? e.message : 'Something went wrong');
      setStatus('error');
    }
  }

  return { status, errorMessage, data, fetch };
}
