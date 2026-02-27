import React, { useState } from 'react';
import {
  ScrollView,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useMoodCheckin } from '@/hooks/useMood';

const TINT = '#2f95dc';

const VALID_TAGS = [
  { key: 'anxious', label: 'Anxious' },
  { key: 'stressed', label: 'Stressed' },
  { key: 'low_energy', label: 'Low Energy' },
  { key: 'restless', label: 'Restless' },
  { key: 'sad', label: 'Sad' },
  { key: 'angry', label: 'Angry' },
  { key: 'calm', label: 'Calm' },
  { key: 'happy', label: 'Happy' },
  { key: 'energetic', label: 'Energetic' },
  { key: 'focused', label: 'Focused' },
  { key: 'grateful', label: 'Grateful' },
  { key: 'overwhelmed', label: 'Overwhelmed' },
];

const SCORES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

function SuccessView({ onReset }: { onReset: () => void }) {
  return (
    <View style={styles.successContainer}>
      <Text style={styles.successMark}>✓</Text>
      <Text style={styles.successHeading}>Check-in logged</Text>
      <Text style={styles.successBody}>Your mood has been recorded.</Text>
      <TouchableOpacity style={styles.button} onPress={onReset}>
        <Text style={styles.buttonText}>Log another</Text>
      </TouchableOpacity>
    </View>
  );
}

export default function CheckInScreen() {
  const [score, setScore] = useState<number>(5);
  const [journal, setJournal] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const { status, errorMessage, submit, reset } = useMoodCheckin();

  function toggleTag(key: string) {
    setSelectedTags(prev =>
      prev.includes(key) ? prev.filter(t => t !== key) : [...prev, key]
    );
  }

  async function handleSubmit() {
    await submit({
      mood_score: score,
      ...(journal.trim() ? { journal_text: journal.trim() } : {}),
      ...(selectedTags.length > 0 ? { manual_tags: selectedTags } : {}),
    });
  }

  function handleReset() {
    reset();
    setScore(5);
    setJournal('');
    setSelectedTags([]);
  }

  if (status === 'success') {
    return <SuccessView onReset={handleReset} />;
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.flex}
    >
      <ScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.heading}>How are you feeling?</Text>
          <Text style={styles.subheading}>
            Log your mood to track patterns over time.
          </Text>
        </View>

        {/* Mood Score */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Mood Score</Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.scoreRow}
          >
            {SCORES.map(n => (
              <TouchableOpacity
                key={n}
                style={[styles.scoreBox, score === n && styles.scoreBoxSelected]}
                onPress={() => setScore(n)}
                activeOpacity={0.7}
              >
                <Text style={[styles.scoreText, score === n && styles.scoreTextSelected]}>
                  {n}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <View style={styles.scoreLabels}>
            <Text style={styles.scoreLabelText}>Very Low</Text>
            <Text style={styles.scoreLabelText}>Neutral</Text>
            <Text style={styles.scoreLabelText}>Great</Text>
          </View>
        </View>

        {/* Journal */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Journal</Text>
          <TextInput
            style={styles.textInput}
            placeholder="What's on your mind? (optional)"
            placeholderTextColor="#AAAAAA"
            value={journal}
            onChangeText={setJournal}
            maxLength={1000}
            multiline
            numberOfLines={3}
            textAlignVertical="top"
          />
          <Text style={styles.charCount}>{journal.length}/1000</Text>
        </View>

        {/* Tags */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>How would you describe it?</Text>
          <View style={styles.tagRow}>
            {VALID_TAGS.map(tag => {
              const selected = selectedTags.includes(tag.key);
              return (
                <TouchableOpacity
                  key={tag.key}
                  style={[styles.pill, selected && styles.pillSelected]}
                  onPress={() => toggleTag(tag.key)}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.pillText, selected && styles.pillTextSelected]}>
                    {tag.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>

        {/* Submit */}
        <TouchableOpacity
          style={[styles.button, status === 'loading' && styles.buttonDisabled]}
          onPress={handleSubmit}
          disabled={status === 'loading'}
          activeOpacity={0.8}
        >
          {status === 'loading' ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text style={styles.buttonText}>Log Check-In</Text>
          )}
        </TouchableOpacity>

        {/* Error */}
        {status === 'error' && errorMessage && (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{errorMessage}</Text>
          </View>
        )}

        <View style={styles.disclaimer}>
          <Text style={styles.disclaimerText}>
            MindRep is a wellness tool, not a medical device.
          </Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  scroll: {
    paddingHorizontal: 24,
    paddingTop: 32,
    paddingBottom: 48,
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
  scoreRow: {
    flexDirection: 'row',
    gap: 8,
    paddingBottom: 4,
  },
  scoreBox: {
    width: 44,
    height: 44,
    borderRadius: 6,
    backgroundColor: '#F5F5F5',
    alignItems: 'center',
    justifyContent: 'center',
  },
  scoreBoxSelected: {
    backgroundColor: TINT,
  },
  scoreText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#999999',
  },
  scoreTextSelected: {
    color: '#FFFFFF',
  },
  scoreLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
    paddingHorizontal: 2,
  },
  scoreLabelText: {
    fontSize: 12,
    color: '#AAAAAA',
  },
  textInput: {
    backgroundColor: '#F8F8F8',
    borderWidth: 1,
    borderColor: '#E8E8E8',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 14,
    fontSize: 15,
    color: '#1A1A1A',
    lineHeight: 22,
    minHeight: 90,
  },
  charCount: {
    marginTop: 6,
    fontSize: 12,
    color: '#CCCCCC',
    textAlign: 'right',
  },
  tagRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  pill: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: '#F0F0F0',
  },
  pillSelected: {
    backgroundColor: TINT,
  },
  pillText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#555555',
  },
  pillTextSelected: {
    color: '#FFFFFF',
  },
  button: {
    backgroundColor: TINT,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 4,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFFFFF',
    letterSpacing: 0.2,
  },
  errorBox: {
    marginTop: 16,
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
  disclaimer: {
    marginTop: 24,
    alignItems: 'center',
  },
  disclaimerText: {
    fontSize: 12,
    color: '#CCCCCC',
    textAlign: 'center',
  },
  successContainer: {
    flex: 1,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  successMark: {
    fontSize: 64,
    color: TINT,
    fontWeight: '300',
    marginBottom: 16,
  },
  successHeading: {
    fontSize: 24,
    fontWeight: '700',
    color: '#1A1A1A',
    marginBottom: 8,
  },
  successBody: {
    fontSize: 15,
    color: '#888888',
    marginBottom: 32,
    textAlign: 'center',
  },
});
