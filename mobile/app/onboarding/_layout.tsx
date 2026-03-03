import { Stack } from 'expo-router';

export default function OnboardingLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="consent" />
      <Stack.Screen name="ai-consent" />
      <Stack.Screen name="health-notice" />
    </Stack>
  );
}
