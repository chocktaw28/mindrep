import FontAwesome from '@expo/vector-icons/FontAwesome';
import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { useFonts } from 'expo-font';
import { Stack, useRouter, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect, useState } from 'react';
import 'react-native-reanimated';
import type { Session } from '@supabase/supabase-js';

import { useColorScheme } from '@/components/useColorScheme';
import { supabase } from '@/services/auth';
import { api } from '@/services/api';

export {
  // Catch any errors thrown by the Layout component.
  ErrorBoundary,
} from 'expo-router';

export const unstable_settings = {
  // Ensure that reloading on `/modal` keeps a back button present.
  initialRouteName: '(tabs)',
};

// Prevent the splash screen from auto-hiding before asset loading is complete.
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [loaded, error] = useFonts({
    SpaceMono: require('../assets/fonts/SpaceMono-Regular.ttf'),
    ...FontAwesome.font,
  });

  // Expo Router uses Error Boundaries to catch errors in the navigation tree.
  useEffect(() => {
    if (error) throw error;
  }, [error]);

  useEffect(() => {
    if (loaded) {
      SplashScreen.hideAsync();
    }
  }, [loaded]);

  if (!loaded) {
    return null;
  }

  return <RootLayoutNav />;
}

// undefined = not yet resolved; null = no session; Session = authenticated
type SessionState = Session | null | undefined;

// undefined = not yet checked; true/false = checked
type ConsentState = boolean | undefined;

function RootLayoutNav() {
  const colorScheme = useColorScheme();
  const router = useRouter();
  const segments = useSegments();
  const [session, setSession] = useState<SessionState>(undefined);
  const [hasConsent, setHasConsent] = useState<ConsentState>(undefined);

  // Sync auth state
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      // Reset consent check on sign-out so it re-runs on next login
      if (!newSession) setHasConsent(undefined);
    });

    return () => subscription.unsubscribe();
  }, []);

  // Once we have a session, check whether onboarding consent has been given
  useEffect(() => {
    if (!session) return;

    api.get<{ mood_data_consent: boolean }>('/users/me')
      .then(data => setHasConsent(data.mood_data_consent))
      .catch(() => {
        // If the endpoint fails (e.g. user row not yet created), treat as
        // no consent and send to onboarding where the row will be upserted.
        setHasConsent(false);
      });
  }, [session]);

  // Route guard
  useEffect(() => {
    // Still resolving auth or consent — don't redirect yet
    if (session === undefined) return;

    const inAuthGroup = segments[0] === 'auth';
    const inOnboardingGroup = segments[0] === 'onboarding';

    // Not logged in → login screen
    if (!session) {
      if (!inAuthGroup) router.replace('/auth/login');
      return;
    }

    // Logged in but consent not yet checked
    if (hasConsent === undefined) return;

    // Logged in, no consent → onboarding
    if (!hasConsent) {
      if (!inOnboardingGroup) router.replace('/onboarding/consent');
      return;
    }

    // Logged in, consent given → main app
    if (inAuthGroup || inOnboardingGroup) {
      router.replace('/(tabs)');
    }
  }, [session, hasConsent, segments]);

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <Stack>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="modal" options={{ presentation: 'modal' }} />
        <Stack.Screen name="auth/login" options={{ headerShown: false }} />
        <Stack.Screen name="onboarding" options={{ headerShown: false }} />
      </Stack>
    </ThemeProvider>
  );
}
