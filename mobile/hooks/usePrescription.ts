import { useState } from 'react';
import { api } from '@/services/api';

export type MoodPrescription = {
  id: string;
  created_at: string;
  exercise_type: string;
  suggested_duration_minutes: number;
  suggested_intensity: string;
  reasoning: string;
  confidence: number;
  source: string;
};

export type PrescriptionResponse = {
  prescription: MoodPrescription | null;
  has_data: boolean;
  disclaimer: string;
};

type Status = 'idle' | 'loading' | 'success' | 'error';

export function usePrescription() {
  const [status, setStatus] = useState<Status>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [data, setData] = useState<PrescriptionResponse | null>(null);

  async function fetch() {
    setStatus('loading');
    setErrorMessage(null);
    try {
      const result = await api.get<PrescriptionResponse>('/prescriptions/today');
      setData(result);
      setStatus('success');
    } catch (e: unknown) {
      setErrorMessage(e instanceof Error ? e.message : 'Something went wrong');
      setStatus('error');
    }
  }

  function reset() {
    setStatus('idle');
    setErrorMessage(null);
    setData(null);
  }

  return { status, errorMessage, data, fetch, reset };
}
