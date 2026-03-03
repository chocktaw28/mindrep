/**
 * Settings Screen
 *
 * Sections:
 *  1. Consent Management  — live toggles for all 3 consent types, saved to backend
 *  2. Health Data         — Connect Apple Health (iOS only), 7-day HealthKit sync
 *  3. Data Export         — request a GDPR Art. 20 export (202 Accepted)
 *  4. Delete All Data     — destructive, confirmation Alert, calls DELETE /users/me
 *  5. Sign Out            — calls signOut() and navigates to /auth/login
 *  6. App info            — version + wellness disclaimer
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  ActivityIndicator,
  Platform,
  ScrollView,
  Switch,
  Text,
  TouchableOpacity,
  View,
  StyleSheet,
} from 'react-native';
import { useRouter } from 'expo-router';
import { signOut } from '@/services/auth';
import { api } from '@/services/api';
import { useHealthKit } from '@/hooks/useHealthKit';

const TINT = '#2f95dc';
const DESTRUCTIVE = '#D32F2F';
const APP_VERSION = '0.1.0';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ConsentState = {
  mood_data_consent: boolean;
  wearable_data_consent: boolean;
  ai_processing_consent: boolean;
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ title }: { title: string }) {
  return <Text style={styles.sectionHeader}>{title}</Text>;
}

function SettingsRow({
  label,
  sublabel,
  right,
  onPress,
  destructive,
}: {
  label: string;
  sublabel?: string;
  right?: React.ReactNode;
  onPress?: () => void;
  destructive?: boolean;
}) {
  return (
    <TouchableOpacity
      style={styles.row}
      onPress={onPress}
      disabled={!onPress}
      activeOpacity={onPress ? 0.6 : 1}
    >
      <View style={styles.rowLeft}>
        <Text style={[styles.rowLabel, destructive && styles.rowLabelDestructive]}>
          {label}
        </Text>
        {sublabel ? <Text style={styles.rowSublabel}>{sublabel}</Text> : null}
      </View>
      {right ? <View style={styles.rowRight}>{right}</View> : null}
    </TouchableOpacity>
  );
}

function Separator() {
  return <View style={styles.separator} />;
}

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

export default function SettingsScreen() {
  const router = useRouter();

  // Consent state
  const [consent, setConsent] = useState<ConsentState | null>(null);
  const [loadingConsent, setLoadingConsent] = useState(true);
  const [savingConsent, setSavingConsent] = useState(false);
  const [consentError, setConsentError] = useState<string | null>(null);

  // Pending save debounce ref
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Apple Health
  const { status: hkStatus, syncResult: hkResult, requestAndSync } = useHealthKit();

  // Export / delete state
  const [exportLoading, setExportLoading] = useState(false);
  const [exportDone, setExportDone] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [signOutLoading, setSignOutLoading] = useState(false);

  // ---------------------------------------------------------------------------
  // Load current consent on mount
  // ---------------------------------------------------------------------------

  useEffect(() => {
    api
      .get<ConsentState>('/users/me')
      .then(data => {
        setConsent({
          mood_data_consent: !!data.mood_data_consent,
          wearable_data_consent: !!data.wearable_data_consent,
          ai_processing_consent: !!data.ai_processing_consent,
        });
      })
      .catch(() => {
        setConsentError('Could not load your consent preferences.');
      })
      .finally(() => setLoadingConsent(false));
  }, []);

  // ---------------------------------------------------------------------------
  // Consent toggle — debounce saves so rapid taps only fire one request
  // ---------------------------------------------------------------------------

  function handleToggle(key: keyof ConsentState, value: boolean) {
    if (!consent) return;

    // mood_data_consent cannot be revoked
    if (key === 'mood_data_consent' && !value) {
      Alert.alert(
        'Required consent',
        'Mood data consent is required to use MindRep. Without it we cannot process your wellbeing data.',
      );
      return;
    }

    const updated = { ...consent, [key]: value };
    setConsent(updated);
    setConsentError(null);

    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      persistConsent(updated);
    }, 600);
  }

  async function persistConsent(payload: ConsentState) {
    setSavingConsent(true);
    try {
      await api.patch('/users/consent', payload);
    } catch {
      setConsentError('Failed to save your preferences. Please try again.');
    } finally {
      setSavingConsent(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Data export
  // ---------------------------------------------------------------------------

  async function handleExport() {
    setExportLoading(true);
    try {
      await api.post('/users/export', {});
      setExportDone(true);
      Alert.alert(
        'Export requested',
        'Your data export has been requested. We will email it to you within 30 days as required by UK GDPR.',
      );
    } catch {
      Alert.alert('Error', 'Could not request your data export. Please try again.');
    } finally {
      setExportLoading(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Delete account
  // ---------------------------------------------------------------------------

  function handleDeletePress() {
    Alert.alert(
      'Delete all data',
      'This will permanently delete your account and all associated data — mood check-ins, wearable data, exercise sessions, and prescriptions. This cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete everything',
          style: 'destructive',
          onPress: confirmDelete,
        },
      ],
    );
  }

  async function confirmDelete() {
    setDeleteLoading(true);
    try {
      await api.delete('/users/me');
      // Sign out locally — auth state change will redirect to login
      await signOut();
    } catch {
      setDeleteLoading(false);
      Alert.alert('Error', 'Could not delete your account. Please try again or contact support.');
    }
  }

  // ---------------------------------------------------------------------------
  // Apple Health — request permissions + initial 7-day sync
  // ---------------------------------------------------------------------------

  function handleHealthKitConnect() {
    if (Platform.OS !== 'ios') {
      Alert.alert('Not available', 'Apple Health is only available on iPhone.');
      return;
    }
    requestAndSync();
  }

  // Show result Alert when hkStatus settles to a terminal state
  useEffect(() => {
    if (hkStatus === 'success') {
      const { daysSynced = 0, daysAttempted = 0 } = hkResult ?? {};
      Alert.alert(
        'Apple Health connected',
        `Synced ${daysSynced} of ${daysAttempted} day${daysAttempted !== 1 ? 's' : ''} of health data.`,
      );
    } else if (hkStatus === 'denied') {
      Alert.alert(
        'Permission denied',
        'MindRep needs Health access to read your wellbeing data. You can enable it in Settings > Privacy & Security > Health > MindRep.',
      );
    } else if (hkStatus === 'error' && hkResult) {
      const summary = hkResult.errors.length > 0
        ? `${hkResult.daysSynced}/${hkResult.daysAttempted} days synced.\n\n${hkResult.errors[0]}`
        : 'Could not read health data. Please try again.';
      Alert.alert('Sync issue', summary);
    }
  }, [hkStatus]);

  // ---------------------------------------------------------------------------
  // Sign out
  // ---------------------------------------------------------------------------

  async function handleSignOut() {
    setSignOutLoading(true);
    try {
      await signOut();
      router.replace('/auth/login');
    } catch {
      setSignOutLoading(false);
      Alert.alert('Error', 'Could not sign out. Please try again.');
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <ScrollView
      contentContainerStyle={styles.scroll}
      showsVerticalScrollIndicator={false}
    >
      {/* ------------------------------------------------------------------ */}
      {/* 1. Consent Management                                               */}
      {/* ------------------------------------------------------------------ */}
      <SectionHeader title="Consent Management" />
      <View style={styles.group}>
        {loadingConsent ? (
          <View style={styles.loadingRow}>
            <ActivityIndicator color={TINT} size="small" />
            <Text style={styles.loadingText}>Loading preferences…</Text>
          </View>
        ) : (
          <>
            <SettingsRow
              label="Mood and journal data"
              sublabel="Required — enables check-ins and insights"
              right={
                <Switch
                  value={consent?.mood_data_consent ?? true}
                  onValueChange={v => handleToggle('mood_data_consent', v)}
                  trackColor={{ true: TINT }}
                  ios_backgroundColor="#E5E5EA"
                />
              }
            />
            <Separator />
            <SettingsRow
              label="Wearable and health data"
              sublabel="Optional — enables HealthKit and Oura sync"
              right={
                <Switch
                  value={consent?.wearable_data_consent ?? false}
                  onValueChange={v => handleToggle('wearable_data_consent', v)}
                  trackColor={{ true: TINT }}
                  ios_backgroundColor="#E5E5EA"
                />
              }
            />
            <Separator />
            <SettingsRow
              label="AI mood classification"
              sublabel="Optional — anonymised text sent to Claude for mood labels"
              right={
                <Switch
                  value={consent?.ai_processing_consent ?? false}
                  onValueChange={v => handleToggle('ai_processing_consent', v)}
                  trackColor={{ true: TINT }}
                  ios_backgroundColor="#E5E5EA"
                />
              }
            />
            {savingConsent && (
              <View style={styles.savingRow}>
                <ActivityIndicator color={TINT} size="small" />
                <Text style={styles.savingText}>Saving…</Text>
              </View>
            )}
            {consentError && !savingConsent && (
              <View style={styles.inlineError}>
                <Text style={styles.inlineErrorText}>{consentError}</Text>
              </View>
            )}
          </>
        )}
      </View>

      {/* ------------------------------------------------------------------ */}
      {/* 2. Apple Health                                                     */}
      {/* ------------------------------------------------------------------ */}
      {Platform.OS === 'ios' && (
        <>
          <SectionHeader title="Health Data" />
          <View style={styles.group}>
            <SettingsRow
              label={
                hkStatus === 'requesting'
                  ? 'Requesting access…'
                  : hkStatus === 'syncing'
                  ? 'Syncing health data…'
                  : hkStatus === 'success'
                  ? 'Apple Health connected'
                  : 'Connect Apple Health'
              }
              sublabel={
                hkStatus === 'success' && hkResult
                  ? `Last synced ${hkResult.daysSynced} day${hkResult.daysSynced !== 1 ? 's' : ''}`
                  : hkStatus === 'denied'
                  ? 'Permission denied — tap to open Health settings'
                  : 'Sync HRV, sleep, steps and workouts'
              }
              onPress={
                hkStatus === 'requesting' || hkStatus === 'syncing'
                  ? undefined
                  : handleHealthKitConnect
              }
              right={
                hkStatus === 'requesting' || hkStatus === 'syncing' ? (
                  <ActivityIndicator color={TINT} size="small" />
                ) : hkStatus === 'success' ? (
                  <Text style={styles.doneText}>Connected</Text>
                ) : (
                  <Text style={styles.chevron}>›</Text>
                )
              }
            />
          </View>
        </>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* 3. Data Export                                                      */}
      {/* ------------------------------------------------------------------ */}
      <SectionHeader title="Your Data" />
      <View style={styles.group}>
        <SettingsRow
          label={exportDone ? 'Export requested' : 'Request data export'}
          sublabel="Receive a copy of all your data (UK GDPR Art. 20)"
          onPress={exportDone || exportLoading ? undefined : handleExport}
          right={
            exportLoading ? (
              <ActivityIndicator color={TINT} size="small" />
            ) : exportDone ? (
              <Text style={styles.doneText}>Requested</Text>
            ) : (
              <Text style={styles.chevron}>›</Text>
            )
          }
        />
      </View>

      {/* ------------------------------------------------------------------ */}
      {/* 4. Delete All Data                                                  */}
      {/* ------------------------------------------------------------------ */}
      <View style={[styles.group, styles.groupSpacing]}>
        <SettingsRow
          label={deleteLoading ? 'Deleting…' : 'Delete all data'}
          sublabel="Permanently removes your account and all records"
          destructive
          onPress={deleteLoading ? undefined : handleDeletePress}
          right={
            deleteLoading ? (
              <ActivityIndicator color={DESTRUCTIVE} size="small" />
            ) : (
              <Text style={[styles.chevron, { color: DESTRUCTIVE }]}>›</Text>
            )
          }
        />
      </View>

      {/* ------------------------------------------------------------------ */}
      {/* 5. Sign Out                                                         */}
      {/* ------------------------------------------------------------------ */}
      <SectionHeader title="Account" />
      <View style={styles.group}>
        <SettingsRow
          label={signOutLoading ? 'Signing out…' : 'Sign out'}
          onPress={signOutLoading ? undefined : handleSignOut}
          right={
            signOutLoading ? (
              <ActivityIndicator color={TINT} size="small" />
            ) : (
              <Text style={styles.chevron}>›</Text>
            )
          }
        />
      </View>

      {/* ------------------------------------------------------------------ */}
      {/* 6. App Info                                                         */}
      {/* ------------------------------------------------------------------ */}
      <View style={styles.appInfo}>
        <Text style={styles.appName}>MindRep</Text>
        <Text style={styles.appVersion}>Version {APP_VERSION}</Text>
        <Text style={styles.disclaimer}>
          MindRep is a wellness tool, not a medical device. It does not diagnose or treat any health
          condition. Always consult a qualified healthcare professional for medical concerns.
        </Text>
      </View>
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  scroll: {
    paddingTop: 20,
    paddingBottom: 48,
    backgroundColor: '#F2F2F7',
  },
  // Section header (above each group)
  sectionHeader: {
    fontSize: 13,
    fontWeight: '600',
    color: '#6C6C70',
    letterSpacing: 0.3,
    textTransform: 'uppercase',
    paddingHorizontal: 20,
    paddingTop: 28,
    paddingBottom: 8,
  },
  // Group — white card with rounded corners
  group: {
    backgroundColor: '#FFFFFF',
    marginHorizontal: 16,
    borderRadius: 12,
    overflow: 'hidden',
  },
  groupSpacing: {
    marginTop: 12,
  },
  // Row
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 13,
    minHeight: 52,
  },
  rowLeft: {
    flex: 1,
    paddingRight: 12,
  },
  rowLabel: {
    fontSize: 16,
    color: '#1C1C1E',
  },
  rowLabelDestructive: {
    color: DESTRUCTIVE,
  },
  rowSublabel: {
    fontSize: 13,
    color: '#8E8E93',
    marginTop: 2,
    lineHeight: 18,
  },
  rowRight: {
    alignItems: 'flex-end',
    justifyContent: 'center',
    minWidth: 24,
  },
  chevron: {
    fontSize: 22,
    color: '#C7C7CC',
    lineHeight: 24,
    fontWeight: '300',
  },
  // Separator between rows
  separator: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: '#E5E5EA',
    marginLeft: 16,
  },
  // Loading row (while fetching consent)
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 16,
    paddingVertical: 18,
  },
  loadingText: {
    fontSize: 14,
    color: '#8E8E93',
  },
  // Saving indicator (below consent toggles)
  savingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#E5E5EA',
  },
  savingText: {
    fontSize: 13,
    color: TINT,
  },
  // Inline error (below consent toggles)
  inlineError: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#E5E5EA',
  },
  inlineErrorText: {
    fontSize: 13,
    color: DESTRUCTIVE,
    lineHeight: 18,
  },
  // Export "Requested" label
  doneText: {
    fontSize: 13,
    color: '#8E8E93',
  },
  // App info footer
  appInfo: {
    alignItems: 'center',
    marginTop: 40,
    paddingHorizontal: 32,
    paddingBottom: 8,
  },
  appName: {
    fontSize: 15,
    fontWeight: '600',
    color: '#8E8E93',
    letterSpacing: 0.3,
  },
  appVersion: {
    fontSize: 13,
    color: '#AEAEB2',
    marginTop: 4,
    marginBottom: 16,
  },
  disclaimer: {
    fontSize: 12,
    color: '#AEAEB2',
    textAlign: 'center',
    lineHeight: 18,
  },
});
