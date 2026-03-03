/**
 * Onboarding Step 1 — Data Processing Consent
 *
 * Collects:
 *   • mood_data_consent      (REQUIRED — enables the core product)
 *   • wearable_data_consent  (OPTIONAL — enables HealthKit/Oura sync)
 *
 * Values are passed forward as route params to avoid extra state management.
 * All consent fields are persisted at the end of screen 3.
 */
import React, { useState } from 'react';
import {
  ScrollView,
  View,
  Text,
  Switch,
  TouchableOpacity,
  StyleSheet,
} from 'react-native';
import { useRouter } from 'expo-router';

const TINT = '#2f95dc';

export default function ConsentScreen() {
  const router = useRouter();
  const [moodConsent, setMoodConsent] = useState(false);
  const [wearableConsent, setWearableConsent] = useState(false);

  function handleContinue() {
    router.push({
      pathname: '/onboarding/ai-consent',
      params: {
        mood_data_consent: moodConsent ? '1' : '0',
        wearable_data_consent: wearableConsent ? '1' : '0',
      },
    });
  }

  return (
    <ScrollView
      contentContainerStyle={styles.scroll}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.header}>
        <Text style={styles.step}>Step 1 of 3</Text>
        <Text style={styles.heading}>Your data, your choice</Text>
        <Text style={styles.subheading}>
          MindRep needs your permission to store and use your wellbeing data.
          You can update these at any time in Settings.
        </Text>
      </View>

      {/* Mood data — required */}
      <View style={styles.card}>
        <View style={styles.cardRow}>
          <View style={styles.cardText}>
            <Text style={styles.cardTitle}>Mood and journal data</Text>
            <Text style={styles.cardBadgeRequired}>Required</Text>
          </View>
          <Switch
            value={moodConsent}
            onValueChange={setMoodConsent}
            trackColor={{ false: '#E0E0E0', true: TINT }}
            thumbColor="#FFFFFF"
          />
        </View>
        <Text style={styles.cardBody}>
          Allows MindRep to store your daily mood scores and optional journal
          entries. This is the core of the product — without it we cannot track
          your wellbeing patterns over time.
        </Text>
        <View style={styles.dataPoints}>
          <Text style={styles.dataPointLabel}>What we store</Text>
          <Text style={styles.dataPoint}>• Mood score (1–10) per check-in</Text>
          <Text style={styles.dataPoint}>• Journal text (optional, stays on our servers only)</Text>
          <Text style={styles.dataPoint}>• Tags you select (e.g. Anxious, Calm, Energetic)</Text>
        </View>
      </View>

      {/* Wearable data — optional */}
      <View style={styles.card}>
        <View style={styles.cardRow}>
          <View style={styles.cardText}>
            <Text style={styles.cardTitle}>Wearable and health data</Text>
            <Text style={styles.cardBadgeOptional}>Optional</Text>
          </View>
          <Switch
            value={wearableConsent}
            onValueChange={setWearableConsent}
            trackColor={{ false: '#E0E0E0', true: TINT }}
            thumbColor="#FFFFFF"
          />
        </View>
        <Text style={styles.cardBody}>
          Allows MindRep to read daily biometric summaries from Apple Health
          or Oura Ring. Enables the correlation engine — we can show you which
          types of exercise most improve your mood.
        </Text>
        <View style={styles.dataPoints}>
          <Text style={styles.dataPointLabel}>What we read</Text>
          <Text style={styles.dataPoint}>• Heart rate variability (HRV)</Text>
          <Text style={styles.dataPoint}>• Resting heart rate</Text>
          <Text style={styles.dataPoint}>• Sleep duration and quality score</Text>
          <Text style={styles.dataPoint}>• Step count and active energy</Text>
          <Text style={styles.dataPointNote}>
            Biometric data never leaves our infrastructure.
          </Text>
        </View>
      </View>

      <TouchableOpacity
        style={[styles.button, !moodConsent && styles.buttonDisabled]}
        onPress={handleContinue}
        disabled={!moodConsent}
        activeOpacity={0.8}
      >
        <Text style={styles.buttonText}>Continue</Text>
      </TouchableOpacity>

      {!moodConsent && (
        <Text style={styles.hint}>
          Mood data consent is required to continue.
        </Text>
      )}

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
  cardRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  cardText: {
    flex: 1,
    marginRight: 12,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1A1A1A',
    marginBottom: 4,
  },
  cardBadgeRequired: {
    fontSize: 11,
    fontWeight: '700',
    color: '#C0392B',
    letterSpacing: 0.4,
    textTransform: 'uppercase',
  },
  cardBadgeOptional: {
    fontSize: 11,
    fontWeight: '600',
    color: '#888888',
    letterSpacing: 0.4,
    textTransform: 'uppercase',
  },
  cardBody: {
    fontSize: 14,
    color: '#555555',
    lineHeight: 21,
    marginBottom: 14,
  },
  dataPoints: {
    backgroundColor: '#FFFFFF',
    borderRadius: 10,
    padding: 14,
    borderWidth: 1,
    borderColor: '#EEEEEE',
  },
  dataPointLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: '#AAAAAA',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  dataPoint: {
    fontSize: 13,
    color: '#444444',
    lineHeight: 20,
  },
  dataPointNote: {
    fontSize: 12,
    color: '#AAAAAA',
    marginTop: 8,
    fontStyle: 'italic',
  },
  button: {
    backgroundColor: TINT,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 8,
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
  hint: {
    marginTop: 10,
    fontSize: 13,
    color: '#C0392B',
    textAlign: 'center',
  },
  disclaimer: {
    marginTop: 24,
    fontSize: 12,
    color: '#CCCCCC',
    textAlign: 'center',
  },
});
