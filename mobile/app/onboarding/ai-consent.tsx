/**
 * Onboarding Step 2 — AI Processing Consent
 *
 * Collects:
 *   • ai_processing_consent  (OPTIONAL — enables Claude mood classification)
 *
 * Receives mood_data_consent and wearable_data_consent from screen 1 via
 * route params, passes all three forward to screen 3.
 *
 * "Use manual labels instead" is the explicit opt-out path — the user can
 * still use all tags and get recommendations, just without AI classification
 * of their journal text.
 */
import React, { useState } from 'react';
import {
  ScrollView,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';

const TINT = '#2f95dc';

export default function AiConsentScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    mood_data_consent: string;
    wearable_data_consent: string;
  }>();

  const [aiConsent, setAiConsent] = useState<boolean | null>(null);

  function handleContinue(choice: boolean) {
    setAiConsent(choice);
    router.push({
      pathname: '/onboarding/health-notice',
      params: {
        mood_data_consent: params.mood_data_consent ?? '0',
        wearable_data_consent: params.wearable_data_consent ?? '0',
        ai_processing_consent: choice ? '1' : '0',
      },
    });
  }

  return (
    <ScrollView
      contentContainerStyle={styles.scroll}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.header}>
        <Text style={styles.step}>Step 2 of 3</Text>
        <Text style={styles.heading}>Smarter mood insights</Text>
        <Text style={styles.subheading}>
          MindRep can use AI to understand the themes in your journal entries
          and give you richer wellbeing insights.
        </Text>
      </View>

      {/* How it works */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>How AI processing works</Text>
        <View style={styles.step_row}>
          <View style={styles.stepBubble}>
            <Text style={styles.stepNumber}>1</Text>
          </View>
          <Text style={styles.stepText}>
            You write a journal entry during a check-in.
          </Text>
        </View>
        <View style={styles.step_row}>
          <View style={styles.stepBubble}>
            <Text style={styles.stepNumber}>2</Text>
          </View>
          <Text style={styles.stepText}>
            Before leaving our servers, your text is anonymised — names,
            locations, and any identifiable details are removed.
          </Text>
        </View>
        <View style={styles.step_row}>
          <View style={styles.stepBubble}>
            <Text style={styles.stepNumber}>3</Text>
          </View>
          <Text style={styles.stepText}>
            The anonymised text is sent to Claude (Anthropic) for mood
            classification — we receive a label and themes, not your words.
          </Text>
        </View>
        <View style={[styles.step_row, { marginBottom: 0 }]}>
          <View style={styles.stepBubble}>
            <Text style={styles.stepNumber}>4</Text>
          </View>
          <Text style={styles.stepText}>
            The mood label and themes are stored and used to improve your
            personalised exercise recommendations.
          </Text>
        </View>
      </View>

      {/* What you get */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>With AI processing enabled</Text>
        <Text style={styles.benefit}>
          Structured mood labels (e.g. Anxious, Fatigued, Optimistic)
        </Text>
        <Text style={styles.benefit}>
          Recurring themes identified across your entries
        </Text>
        <Text style={styles.benefit}>
          More personalised exercise recommendations
        </Text>
        <View style={styles.divider} />
        <Text style={styles.privacyNote}>
          Your raw journal text is never sent externally. Only anonymised
          fragments are processed. You can withdraw this consent at any time.
        </Text>
      </View>

      {/* CTA — opt in */}
      <TouchableOpacity
        style={styles.button}
        onPress={() => handleContinue(true)}
        activeOpacity={0.8}
      >
        <Text style={styles.buttonText}>Enable AI insights</Text>
      </TouchableOpacity>

      {/* CTA — opt out */}
      <TouchableOpacity
        style={styles.secondaryButton}
        onPress={() => handleContinue(false)}
        activeOpacity={0.7}
      >
        <Text style={styles.secondaryButtonText}>Use manual labels instead</Text>
      </TouchableOpacity>

      <Text style={styles.optOutNote}>
        Choosing manual labels means you select mood tags yourself. You can
        enable AI processing later in Settings.
      </Text>

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
    marginBottom: 16,
  },
  step_row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 14,
  },
  stepBubble: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: TINT,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
    marginTop: 1,
    flexShrink: 0,
  },
  stepNumber: {
    fontSize: 12,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  stepText: {
    flex: 1,
    fontSize: 14,
    color: '#444444',
    lineHeight: 21,
  },
  benefit: {
    fontSize: 14,
    color: '#444444',
    lineHeight: 22,
    paddingLeft: 4,
    marginBottom: 4,
  },
  divider: {
    height: 1,
    backgroundColor: '#EEEEEE',
    marginVertical: 14,
  },
  privacyNote: {
    fontSize: 13,
    color: '#888888',
    lineHeight: 20,
    fontStyle: 'italic',
  },
  button: {
    backgroundColor: TINT,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
    marginBottom: 12,
  },
  buttonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFFFFF',
    letterSpacing: 0.2,
  },
  secondaryButton: {
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#DDDDDD',
  },
  secondaryButtonText: {
    fontSize: 15,
    fontWeight: '500',
    color: '#555555',
  },
  optOutNote: {
    marginTop: 12,
    fontSize: 13,
    color: '#AAAAAA',
    textAlign: 'center',
    lineHeight: 19,
  },
  disclaimer: {
    marginTop: 24,
    fontSize: 12,
    color: '#CCCCCC',
    textAlign: 'center',
  },
});
