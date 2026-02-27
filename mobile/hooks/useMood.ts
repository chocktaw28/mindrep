import { useState } from 'react';
import { api } from '@/services/api';

export type MoodClassification = {
  mood_label: string;
  intensity: number;
  themes: string[];
  confidence: number;
};

export type CheckinResponse = {
  id: string;
  created_at: string;
  mood_score: number;
  journal_text_stored: boolean;
  ai_processed: boolean;
  classification: MoodClassification | null;
  manual_tags: string[] | null;
};

type Status = 'idle' | 'loading' | 'success' | 'error';

export function useMoodCheckin() {
  const [status, setStatus] = useState<Status>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [result, setResult] = useState<CheckinResponse | null>(null);

  async function submit(payload: {
    mood_score: number;
    journal_text?: string;
    manual_tags?: string[];
  }) {
    setStatus('loading');
    setErrorMessage(null);
    try {
      const data = await api.post<CheckinResponse>('/mood/checkin', payload);
      setResult(data);
      setStatus('success');
    } catch (e: unknown) {
      setErrorMessage(e instanceof Error ? e.message : 'Something went wrong');
      setStatus('error');
    }
  }

  function reset() {
    setStatus('idle');
    setErrorMessage(null);
    setResult(null);
  }

  return { status, errorMessage, result, submit, reset };
}
