import { createClient } from '@supabase/supabase-js';
import AsyncStorage from '@react-native-async-storage/async-storage';

// TODO: replace with your project values from Supabase dashboard → Settings → API
const SUPABASE_URL = 'https://ajulobmflxgoqigziqve.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFqdWxvYm1mbHhnb3FpZ3ppcXZlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIxMzA1MjgsImV4cCI6MjA4NzcwNjUyOH0.qbzEw14d3NkOV1IHAiPg1f0NrYLQH04gR33EgqfThD4';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    storage: AsyncStorage,
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: false, // must be false for React Native
  },
});

export async function signInWithMagicLink(email: string): Promise<void> {
  const { error } = await supabase.auth.signInWithOtp({ email });
  if (error) throw error;
}

export async function signOut(): Promise<void> {
  const { error } = await supabase.auth.signOut();
  if (error) throw error;
}

export async function getSession() {
  const { data } = await supabase.auth.getSession();
  return data.session;
}
