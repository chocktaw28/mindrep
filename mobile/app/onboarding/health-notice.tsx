/**
 * Onboarding Step 3 — Health Data Special Notice
 *
 * Displays the special category data notice required under UK GDPR Art. 9
 * for processing health / biometric data. The user must actively acknowledge
 * before we persist any consent.
 *
 * On "I understand, let's start":
 *   1. Calls PATCH /api/v1/users/consent with all three consent values
 *   2. Navigates to (tabs) on success
 *
 * Route params received from screen 2:
 *   mood_data_consent, wearable_data_consent, ai_processing_consent
 */
import React, { useState } from 'react';
import {
  ScrollView,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { useConsent } from '@/hooks/useConsent';

const TINT = '#2f95dc';

export default function HealthNoticeScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    mood_data_consent: string;
    wearable_data_consent: string;
    ai_processing_consent: string;
  }>();
  const { status, errorMessage, submitConsent } = useConsent();
  const [acknowledged, setAcknowledged] = useState(false);

  async function handleFinish() {
    const payload = {
      mood_data_consent: params.mood_data_consent === '1',
      wearable_data_consent: params.wearable_data_consent === '1',
      ai_processing_consent: params.ai_processing_consent === '1',
    };

    const ok = await submitConsent(payload);
    if (ok) {
      router.replace('/(tabs)');
    }
  }

  const isLoading = status === 'loading';

  return (
    <ScrollView
      contentContainerStyle={styles.scroll}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.header}>
        <Text style={styles.step}>Step 3 of 3</Text>
        <Text style={styles.heading}>Health data notice</Text>
        <Text style={styles.subheading}>
          Before you start, please read this short notice about how MindRep
          handles your health-related data.
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Special category data</Text>
        <Text style={styles.cardBody}>
          Mood scores, journal entries, and biometric data (heart rate, HRV,
          sleep) are classified as special category data under UK GDPR Article
          9. We process this data only on the basis of your explicit consent,
          given on the previous screens.
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>How we protect your data</Text>
        <Text style={styles.listItem}>
          Your data is stored in a Supabase database hosted in the EU (Ireland).
        </Text>
        <Text style={styles.listItem}>
          Row-level security ensures only you can access your records.
        </Text>
        <Text style={styles.listItem}>
          Journal text is anonymised before any AI processing — your name and
          identifying details are stripped before anything leaves our servers.
        </Text>
        <Text style={styles.listItem}>
          Biometric data is never shared with third parties.
        </Text>
        <Text style={styles.listItem}>
          You can delete your account and all associated data at any time from
          Settings.
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Not a medical device</Text>
        <Text style={styles.cardBody}>
          MindRep provides wellbeing insights and exercise suggestions. It does
          not diagnose or treat any health condition. Always consult a qualified
          healthcare professional for medical concerns.
        </Text>
      </View>

      {/* Acknowledgement toggle */}
      <TouchableOpacity
        style={styles.ackRow}
        onPress={() => setAcknowledged(prev => !prev)}
        activeOpacity={0.7}
      >
        <View style={[styles.checkbox, acknowledged && styles.checkboxChecked]}>
          {acknowledged && <Text style={styles.checkmark}>✓</Text>}
        </View>
        <Text style={styles.ackText}>
          I have read this notice and understand how MindRep uses my health data.
        </Text>
      </TouchableOpacity>

      {status === 'error' && errorMessage && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{errorMessage}</Text>
        </View>
      )}

      <TouchableOpacity
        style={[
          styles.button,
          (!acknowledged || isLoading) && styles.buttonDisabled,
        ]}
        onPress={handleFinish}
        disabled={!acknowledged || isLoading}
        activeOpacity={0.8}
      >
        {isLoading ? (
          <ActivityIndicator color="#FFFFFF" />
        ) : (
          <Text style={styles.buttonText}>I understand, let's start</Text>
        )}
      </TouchableOpacity>

      <Text style={styles.disclaimer}>
        MindRep is a wellness tool, not a medical device.
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: {
    paddingHorizontal: 24,
    paddingTop: 40,
    paddingBottom: 48,
    backgroundColor: '#FFFFFF',
  },
  header: {
    marginBottom: 28,
  },
  step: {
    fontSize: 12,
    fontWeight: '600',
    color: TINT,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  heading: {
    fontSize: 26,
    fontWeight: '700',
    color: '#1A1A1A',
    letterSpacing: -0.5,
    marginBottom: 10,
  },
  subheading: {
    fontSize: 15,
    color: '#666666',
    lineHeight: 22,
  },
  card: {
    backgroundColor: '#F8F8F8',
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: '#EEEEEE',
    marginBottom: 16,
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: '#1A1A1A',
    marginBottom: 10,
  },
  cardBody: {
    fontSize: 14,
    color: '#555555',
    lineHeight: 21,
  },
  listItem: {
    fontSize: 14,
    color: '#555555',
    lineHeight: 21,
    paddingLeft: 4,
    marginBottom: 8,
  },
  ackRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 20,
    paddingHorizontal: 4,
  },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: '#CCCCCC',
    marginRight: 12,
    marginTop: 1,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  checkboxChecked: {
    backgroundColor: TINT,
    borderColor: TINT,
  },
  checkmark: {
    fontSize: 13,
    color: '#FFFFFF',
    fontWeight: '700',
    lineHeight: 16,
  },
  ackText: {
    flex: 1,
    fontSize: 14,
    color: '#333333',
    lineHeight: 21,
  },
  errorBox: {
    marginBottom: 16,
    padding: 14,
    backgroundColor: '#FFF0F0',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#FFCCCC',
  },
  errorText: {
    fontSize: 14,
    color: '#D32F2F',
    lineHeight: 20,
  },
  button: {
    backgroundColor: TINT,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.35,
  },
  buttonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFFFFF',
    letterSpacing: 0.2,
  },
  disclaimer: {
    marginTop: 24,
    fontSize: 12,
    color: '#CCCCCC',
    textAlign: 'center',
  },
});
