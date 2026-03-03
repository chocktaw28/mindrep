import { useState } from 'react';
import { api } from '@/services/api';

export type ConsentPayload = {
  mood_data_consent: boolean;
  wearable_data_consent: boolean;
  ai_processing_consent: boolean;
};

type Status = 'idle' | 'loading' | 'success' | 'error';

export function useConsent() {
  const [status, setStatus] = useState<Status>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function submitConsent(payload: ConsentPayload): Promise<boolean> {
    setStatus('loading');
    setErrorMessage(null);
    try {
      await api.patch('/users/consent', payload);
      setStatus('success');
      return true;
    } catch (e: unknown) {
      setErrorMessage(e instanceof Error ? e.message : 'Something went wrong. Please try again.');
      setStatus('error');
      return false;
    }
  }

  return { status, errorMessage, submitConsent };
}
