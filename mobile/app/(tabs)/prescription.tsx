import React, { useEffect } from 'react';
import {
  ScrollView,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Share,
} from 'react-native';
import { usePrescription } from '@/hooks/usePrescription';

const TINT = '#2f95dc';

function titleCase(str: string): string {
  return str.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export default function PrescriptionScreen() {
  const { status, errorMessage, data, fetch } = usePrescription();

  useEffect(() => {
    fetch();
  }, []);

  async function handleShare() {
    if (!data?.prescription) return;
    const { exercise_type, suggested_duration_minutes, suggested_intensity, reasoning } =
      data.prescription;
    await Share.share({
      message: `My MindRep recommendation: ${titleCase(exercise_type)} for ${suggested_duration_minutes} min at ${titleCase(suggested_intensity)} intensity.\n\n${reasoning}`,
    });
  }

  if (status === 'idle' || status === 'loading') {
    return (
      <View style={styles.centeredContainer}>
        <ActivityIndicator color={TINT} />
        <Text style={styles.loadingText}>Loading your recommendation…</Text>
      </View>
    );
  }

  if (status === 'error') {
    return (
      <View style={styles.centeredContainer}>
        <View style={styles.errorCard}>
          <Text style={styles.errorText}>{errorMessage}</Text>
          <TouchableOpacity style={styles.retryButton} onPress={fetch} activeOpacity={0.8}>
            <Text style={styles.retryButtonText}>Try again</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <ScrollView
      contentContainerStyle={styles.scroll}
      showsVerticalScrollIndicator={false}
    >
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.heading}>Today's Move</Text>
        <Text style={styles.subheading}>Your personalised exercise recommendation.</Text>
      </View>

      <Text style={styles.sectionLabel}>TODAY'S RECOMMENDATION</Text>

      {!data?.has_data || !data.prescription ? (
        /* Empty state */
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>
            Complete your first check-in to get a personalised recommendation.
          </Text>
        </View>
      ) : (
        /* Recommendation card */
        <>
          <View style={styles.card}>
            {/* Exercise type heading */}
            <Text style={styles.exerciseHeading}>
              {titleCase(data.prescription.exercise_type)}
            </Text>

            {/* Duration + intensity subtitle */}
            <Text style={styles.exerciseSubtitle}>
              {data.prescription.suggested_duration_minutes} min
              {'  ·  '}
              {titleCase(data.prescription.suggested_intensity)}
            </Text>

            {/* Divider */}
            <View style={styles.divider} />

            {/* Reasoning */}
            <Text style={styles.reasoning}>{data.prescription.reasoning}</Text>

            {/* Source badge */}
            <View
              style={[
                styles.sourceBadge,
                data.prescription.source === 'correlation'
                  ? styles.sourceBadgeTint
                  : styles.sourceBadgeNeutral,
              ]}
            >
              <Text
                style={[
                  styles.sourceBadgeText,
                  data.prescription.source === 'correlation'
                    ? styles.sourceBadgeTextTint
                    : styles.sourceBadgeTextNeutral,
                ]}
              >
                {data.prescription.source === 'correlation'
                  ? 'Based on your data'
                  : 'Based on research'}
              </Text>
            </View>

            {/* Confidence bar */}
            <View style={styles.confidenceSection}>
              <View style={styles.confidenceHeader}>
                <Text style={styles.confidenceLabel}>Confidence</Text>
                <Text style={styles.confidenceValue}>
                  {Math.round(data.prescription.confidence * 100)}%
                </Text>
              </View>
              <View style={styles.confidenceTrack}>
                <View
                  style={[
                    styles.confidenceFill,
                    { width: `${Math.round(data.prescription.confidence * 100)}%` },
                  ]}
                />
              </View>
            </View>
          </View>

          {/* Share button */}
          <TouchableOpacity
            style={styles.shareButton}
            onPress={handleShare}
            activeOpacity={0.7}
          >
            <Text style={styles.shareButtonText}>Share recommendation</Text>
          </TouchableOpacity>
        </>
      )}

      {/* Disclaimer */}
      <View style={styles.disclaimer}>
        <Text style={styles.disclaimerText}>
          {data?.disclaimer ?? 'MindRep is a wellness tool, not a medical device.'}
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centeredContainer: {
    flex: 1,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
    gap: 12,
  },
  loadingText: {
    fontSize: 14,
    color: '#AAAAAA',
  },
  scroll: {
    paddingHorizontal: 24,
    paddingTop: 32,
    paddingBottom: 48,
    backgroundColor: '#FFFFFF',
  },
  header: {
    marginBottom: 32,
  },
  heading: {
    fontSize: 26,
    fontWeight: '700',
    color: '#1A1A1A',
    letterSpacing: -0.5,
  },
  subheading: {
    marginTop: 6,
    fontSize: 15,
    color: '#888888',
    lineHeight: 22,
  },
  sectionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: '#888888',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    marginBottom: 12,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#E8E8E8',
    padding: 20,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 8,
    elevation: 2,
    marginBottom: 12,
  },
  exerciseHeading: {
    fontSize: 22,
    fontWeight: '700',
    color: '#1A1A1A',
    marginBottom: 4,
  },
  exerciseSubtitle: {
    fontSize: 15,
    color: '#888888',
    marginBottom: 0,
  },
  divider: {
    height: 1,
    backgroundColor: '#F0F0F0',
    marginVertical: 16,
  },
  reasoning: {
    fontSize: 15,
    color: '#444444',
    lineHeight: 24,
    marginBottom: 16,
  },
  sourceBadge: {
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginBottom: 20,
  },
  sourceBadgeTint: {
    borderColor: TINT,
  },
  sourceBadgeNeutral: {
    borderColor: '#CCCCCC',
  },
  sourceBadgeText: {
    fontSize: 12,
    fontWeight: '500',
  },
  sourceBadgeTextTint: {
    color: TINT,
  },
  sourceBadgeTextNeutral: {
    color: '#888888',
  },
  confidenceSection: {
    gap: 6,
  },
  confidenceHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  confidenceLabel: {
    fontSize: 12,
    color: '#AAAAAA',
  },
  confidenceValue: {
    fontSize: 12,
    color: '#AAAAAA',
  },
  confidenceTrack: {
    height: 4,
    backgroundColor: '#F0F0F0',
    borderRadius: 2,
    overflow: 'hidden',
  },
  confidenceFill: {
    height: 4,
    backgroundColor: TINT,
    borderRadius: 2,
  },
  emptyCard: {
    backgroundColor: '#F8F8F8',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#E8E8E8',
    padding: 24,
    alignItems: 'center',
    marginBottom: 12,
  },
  emptyText: {
    fontSize: 15,
    color: '#888888',
    textAlign: 'center',
    lineHeight: 24,
  },
  shareButton: {
    alignItems: 'center',
    paddingVertical: 14,
    marginBottom: 4,
  },
  shareButtonText: {
    fontSize: 15,
    color: TINT,
    fontWeight: '500',
  },
  errorCard: {
    backgroundColor: '#FFF0F0',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#FFCCCC',
    padding: 20,
    alignItems: 'center',
    gap: 12,
  },
  errorText: {
    fontSize: 14,
    color: '#D32F2F',
    textAlign: 'center',
    lineHeight: 20,
  },
  retryButton: {
    backgroundColor: '#D32F2F',
    borderRadius: 8,
    paddingHorizontal: 20,
    paddingVertical: 10,
  },
  retryButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#FFFFFF',
  },
  disclaimer: {
    marginTop: 24,
    alignItems: 'center',
  },
  disclaimerText: {
    fontSize: 12,
    color: '#CCCCCC',
    textAlign: 'center',
  },
});
