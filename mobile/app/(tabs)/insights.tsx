import React, { useEffect, useState } from 'react';
import {
  ScrollView,
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
  LayoutChangeEvent,
} from 'react-native';
import Svg, { Polyline } from 'react-native-svg';
import { useInsights, MoodTrendPoint } from '@/hooks/useInsights';

const TINT = '#2f95dc';
const POSITIVE = '#27AE60';
const NEGATIVE = '#D32F2F';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function titleCase(str: string): string {
  return str.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function formatDateRange(start: string, end: string): string {
  const fmt = (s: string) => {
    const d = new Date(s + 'T12:00:00');
    return d.toLocaleDateString('en-GB', { month: 'short', day: 'numeric' });
  };
  return `${fmt(start)} \u2013 ${fmt(end)}`;
}

function formatDayLabel(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('en-GB', { weekday: 'short' });
}

function formatChangePct(pct: number): string {
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Mood Trend Chart
// ---------------------------------------------------------------------------

const CHART_HEIGHT = 120;
const CHART_PAD_V = 16; // vertical padding inside chart

function MoodTrendChart({ points }: { points: MoodTrendPoint[] }) {
  const [chartWidth, setChartWidth] = useState(0);

  function onLayout(e: LayoutChangeEvent) {
    setChartWidth(e.nativeEvent.layout.width);
  }

  if (points.length < 2) {
    return (
      <View style={styles.chartContainer} onLayout={onLayout}>
        <Text style={styles.chartPlaceholder}>
          Not enough data yet — keep checking in.
        </Text>
      </View>
    );
  }

  const scores = points.map(p => p.mood_score);
  const minScore = Math.min(...scores);
  const maxScore = Math.max(...scores);
  // Pad the y range so line never clips the edges
  const yMin = minScore - 0.5;
  const yMax = maxScore + 0.5;
  const yRange = yMax - yMin || 1;

  const innerH = CHART_HEIGHT - CHART_PAD_V * 2;
  const n = points.length;

  function toX(i: number): number {
    if (n === 1) return chartWidth / 2;
    return (i / (n - 1)) * chartWidth;
  }

  function toY(score: number): number {
    return CHART_PAD_V + ((yMax - score) / yRange) * innerH;
  }

  const polyPoints = points
    .map((p, i) => `${toX(i).toFixed(1)},${toY(p.mood_score).toFixed(1)}`)
    .join(' ');

  return (
    <View>
      {/* Y-axis labels */}
      <View style={styles.chartYLabels}>
        <Text style={styles.chartAxisLabel}>{maxScore.toFixed(1)}</Text>
        <Text style={styles.chartAxisLabel}>{minScore.toFixed(1)}</Text>
      </View>

      {/* SVG chart */}
      <View style={styles.chartContainer} onLayout={onLayout}>
        {chartWidth > 0 && (
          <Svg width={chartWidth} height={CHART_HEIGHT}>
            <Polyline
              points={polyPoints}
              fill="none"
              stroke={TINT}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </Svg>
        )}
      </View>

      {/* X-axis day labels */}
      <View style={styles.chartXLabels}>
        {points.map((p, i) => (
          <Text
            key={i}
            style={[
              styles.chartAxisLabel,
              { flex: 1, textAlign: i === 0 ? 'left' : i === n - 1 ? 'right' : 'center' },
            ]}
          >
            {formatDayLabel(p.date)}
          </Text>
        ))}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

export default function InsightsScreen() {
  const { status, errorMessage, data, fetch } = useInsights();

  useEffect(() => {
    fetch();
  }, []);

  // Loading
  if (status === 'idle' || status === 'loading') {
    return (
      <View style={styles.centeredContainer}>
        <ActivityIndicator color={TINT} />
        <Text style={styles.loadingText}>Loading your insights…</Text>
      </View>
    );
  }

  // Error
  if (status === 'error') {
    return (
      <View style={styles.centeredContainer}>
        <View style={styles.errorCard}>
          <Text style={styles.errorText}>{errorMessage}</Text>
        </View>
      </View>
    );
  }

  if (!data) return null;

  const hasAnyData =
    data.mood_trend.length > 0 ||
    data.top_correlations.length > 0 ||
    Object.keys(data.exercise_summary).length > 0;

  const exerciseEntries = Object.entries(data.exercise_summary);
  const maxCount = exerciseEntries.length > 0
    ? Math.max(...exerciseEntries.map(([, c]) => c))
    : 1;

  return (
    <ScrollView
      contentContainerStyle={styles.scroll}
      showsVerticalScrollIndicator={false}
    >
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.heading}>This Week</Text>
        <Text style={styles.subheading}>
          {formatDateRange(data.week_start, data.week_end)}
        </Text>
      </View>

      {!hasAnyData ? (
        /* Empty state */
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>
            Keep checking in daily — your insights will appear after a week of data.
          </Text>
        </View>
      ) : (
        <>
          {/* ---- Mood Trend ---- */}
          {data.mood_trend.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>Mood Trend</Text>
              <View style={styles.card}>
                <MoodTrendChart points={data.mood_trend} />
              </View>
            </View>
          )}

          {/* ---- Top Correlations ---- */}
          {data.top_correlations.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>What's Working</Text>
              {data.top_correlations.map((corr, i) => {
                const pctColor = corr.mood_change_pct >= 0 ? POSITIVE : NEGATIVE;
                const isSignificant = corr.p_value < 0.05;
                return (
                  <View key={i} style={[styles.card, i > 0 && styles.cardSpacing]}>
                    <View style={styles.corrHeader}>
                      <Text style={styles.corrExercise}>
                        {titleCase(corr.exercise_type)}
                      </Text>
                      <Text style={[styles.corrPct, { color: pctColor }]}>
                        {formatChangePct(corr.mood_change_pct)}
                      </Text>
                    </View>
                    <Text style={styles.corrInsight}>{corr.insight_text}</Text>
                    <View style={styles.corrMeta}>
                      <Text style={styles.corrMetaText}>
                        {corr.sample_size} {corr.sample_size === 1 ? 'session' : 'sessions'}
                      </Text>
                      {isSignificant && (
                        <>
                          <Text style={styles.corrDot}>·</Text>
                          <View style={styles.sigPill}>
                            <Text style={styles.sigPillText}>Significant</Text>
                          </View>
                        </>
                      )}
                    </View>
                  </View>
                );
              })}
            </View>
          )}

          {/* ---- Exercise Summary ---- */}
          {exerciseEntries.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>Activity This Week</Text>
              <View style={styles.card}>
                {exerciseEntries.map(([type, count], i) => (
                  <View key={type} style={[styles.barRow, i > 0 && styles.barRowSpacing]}>
                    <Text style={styles.barLabel}>{titleCase(type)}</Text>
                    <View style={styles.barTrackWrapper}>
                      <View style={styles.barTrack}>
                        <View
                          style={[
                            styles.barFill,
                            { width: `${(count / maxCount) * 100}%` },
                          ]}
                        />
                      </View>
                    </View>
                    <Text style={styles.barCount}>{count}</Text>
                  </View>
                ))}
              </View>
            </View>
          )}
        </>
      )}
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

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
  section: {
    marginBottom: 28,
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
  },
  cardSpacing: {
    marginTop: 10,
  },
  emptyCard: {
    backgroundColor: '#F8F8F8',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#E8E8E8',
    padding: 24,
    alignItems: 'center',
  },
  emptyText: {
    fontSize: 15,
    color: '#888888',
    textAlign: 'center',
    lineHeight: 24,
  },
  errorCard: {
    backgroundColor: '#FFF0F0',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#FFCCCC',
    padding: 20,
    alignItems: 'center',
  },
  errorText: {
    fontSize: 14,
    color: '#D32F2F',
    textAlign: 'center',
    lineHeight: 20,
  },
  // Chart
  chartContainer: {
    height: CHART_HEIGHT,
    justifyContent: 'center',
    alignItems: 'center',
  },
  chartPlaceholder: {
    fontSize: 14,
    color: '#CCCCCC',
    textAlign: 'center',
    lineHeight: 22,
  },
  chartYLabels: {
    position: 'absolute',
    top: 0,
    left: 0,
    height: CHART_HEIGHT,
    justifyContent: 'space-between',
    paddingVertical: CHART_PAD_V,
    zIndex: 1,
  },
  chartXLabels: {
    flexDirection: 'row',
    marginTop: 4,
  },
  chartAxisLabel: {
    fontSize: 10,
    color: '#CCCCCC',
  },
  // Correlation cards
  corrHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  corrExercise: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1A1A1A',
  },
  corrPct: {
    fontSize: 16,
    fontWeight: '700',
  },
  corrInsight: {
    fontSize: 14,
    color: '#555555',
    lineHeight: 22,
    marginBottom: 10,
  },
  corrMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  corrMetaText: {
    fontSize: 12,
    color: '#AAAAAA',
  },
  corrDot: {
    fontSize: 12,
    color: '#CCCCCC',
  },
  sigPill: {
    borderWidth: 1,
    borderColor: '#CCCCCC',
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  sigPillText: {
    fontSize: 11,
    color: '#AAAAAA',
    fontWeight: '500',
  },
  // Exercise bar chart
  barRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  barRowSpacing: {
    marginTop: 14,
  },
  barLabel: {
    fontSize: 14,
    color: '#444444',
    width: 90,
  },
  barTrackWrapper: {
    flex: 1,
  },
  barTrack: {
    height: 6,
    backgroundColor: '#F0F0F0',
    borderRadius: 3,
    overflow: 'hidden',
  },
  barFill: {
    height: 6,
    backgroundColor: TINT,
    borderRadius: 3,
  },
  barCount: {
    fontSize: 13,
    color: '#AAAAAA',
    fontWeight: '500',
    width: 20,
    textAlign: 'right',
  },
});
