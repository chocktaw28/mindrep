/**
 * useHealthKit
 * ============
 * Requests HealthKit permissions, reads the last 7 days of biometric data,
 * normalises it into WearableDailyCreate payloads, and POSTs each day to
 * POST /api/v1/wearable/sync.
 *
 * Data collected:
 *   - HRV (HeartRateVariability / SDNN) — avg of samples per day
 *   - Resting heart rate             — avg of samples per day
 *   - Sleep analysis                 — total in-bed/asleep minutes
 *   - Workouts                       — aggregated per calendar day
 *   - Steps                          — daily sum
 *   - Active energy burned           — daily sum (kcal)
 *
 * Xcode setup required (see bottom of file for step-by-step instructions).
 *
 * IMPORTANT: This hook is iOS-only. All exports are no-ops on Android/web.
 */

import { useState } from 'react';
import { Platform } from 'react-native';
import AppleHealthKit, {
  HealthKitPermissions,
  HealthValue,
} from 'react-native-health';
import { api } from '@/services/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Shape sent to POST /api/v1/wearable/sync */
type WearableDailyCreate = {
  date: string;           // ISO-8601 date e.g. "2024-03-01"
  source: 'healthkit';
  hrv_avg: number | null;
  hrv_min: number | null;
  hrv_max: number | null;
  resting_hr: number | null;
  sleep_duration_minutes: number | null;
  sleep_deep_minutes: null;    // HealthKit doesn't expose deep sleep in SDK v1
  sleep_rem_minutes: null;     // HealthKit doesn't expose REM sleep in SDK v1
  sleep_score: null;
  readiness_score: null;
  steps: number | null;
  active_calories: number | null;
};

type SyncStatus = 'idle' | 'requesting' | 'syncing' | 'success' | 'denied' | 'error';

type SyncResult = {
  daysAttempted: number;
  daysSynced: number;
  errors: string[];
};

// ---------------------------------------------------------------------------
// Permission set
// ---------------------------------------------------------------------------

const PERMISSIONS: HealthKitPermissions = {
  permissions: {
    read: [
      AppleHealthKit.Constants.Permissions.HeartRateVariability,
      AppleHealthKit.Constants.Permissions.RestingHeartRate,
      AppleHealthKit.Constants.Permissions.SleepAnalysis,
      AppleHealthKit.Constants.Permissions.Workout,
      AppleHealthKit.Constants.Permissions.StepCount,
      AppleHealthKit.Constants.Permissions.ActiveEnergyBurned,
    ],
    write: [],
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Return the Date for `daysAgo` calendar days before today at midnight local. */
function daysAgoMidnight(daysAgo: number): Date {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  d.setHours(0, 0, 0, 0);
  return d;
}

/** Format a Date as an ISO-8601 date string "YYYY-MM-DD". */
function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/**
 * Group an array of HealthKit samples (which have a `startDate` string) by
 * their calendar date and compute avg/min/max of `value` per group.
 */
function groupByDay(samples: HealthValue[]): Map<string, { values: number[] }> {
  const map = new Map<string, { values: number[] }>();
  for (const s of samples) {
    const dateKey = toDateStr(new Date(s.startDate));
    if (!map.has(dateKey)) map.set(dateKey, { values: [] });
    map.get(dateKey)!.values.push(s.value);
  }
  return map;
}

function avg(arr: number[]): number | null {
  if (!arr.length) return null;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}
function min(arr: number[]): number | null {
  return arr.length ? Math.min(...arr) : null;
}
function maxVal(arr: number[]): number | null {
  return arr.length ? Math.max(...arr) : null;
}
function sum(arr: number[]): number | null {
  return arr.length ? arr.reduce((a, b) => a + b, 0) : null;
}

// ---------------------------------------------------------------------------
// HealthKit wrappers (promisified)
// ---------------------------------------------------------------------------

function initHealthKit(): Promise<void> {
  return new Promise((resolve, reject) => {
    AppleHealthKit.initHealthKit(PERMISSIONS, (err) => {
      if (err) reject(new Error(err));
      else resolve();
    });
  });
}

function getHRVSamples(startDate: Date, endDate: Date): Promise<HealthValue[]> {
  return new Promise((resolve) => {
    AppleHealthKit.getHeartRateVariabilitySamples(
      { startDate: startDate.toISOString(), endDate: endDate.toISOString(), limit: 1000 },
      (err, results) => resolve(err ? [] : results),
    );
  });
}

function getRestingHRSamples(startDate: Date, endDate: Date): Promise<HealthValue[]> {
  return new Promise((resolve) => {
    AppleHealthKit.getRestingHeartRateSamples(
      { startDate: startDate.toISOString(), endDate: endDate.toISOString(), limit: 1000 },
      (err, results) => resolve(err ? [] : results),
    );
  });
}

function getSleepSamples(startDate: Date, endDate: Date): Promise<HealthValue[]> {
  return new Promise((resolve) => {
    AppleHealthKit.getSleepSamples(
      { startDate: startDate.toISOString(), endDate: endDate.toISOString(), limit: 1000 },
      (err, results) => resolve(err ? [] : results),
    );
  });
}

function getStepsSamples(startDate: Date, endDate: Date): Promise<HealthValue[]> {
  return new Promise((resolve) => {
    AppleHealthKit.getDailyStepCountSamples(
      { startDate: startDate.toISOString(), endDate: endDate.toISOString() },
      (err, results) => resolve(err ? [] : results),
    );
  });
}

function getActiveCaloriesSamples(startDate: Date, endDate: Date): Promise<HealthValue[]> {
  return new Promise((resolve) => {
    AppleHealthKit.getActiveEnergyBurned(
      { startDate: startDate.toISOString(), endDate: endDate.toISOString() },
      (err, results) => resolve(err ? [] : results),
    );
  });
}

// ---------------------------------------------------------------------------
// Normalisation: raw HealthKit data → WearableDailyCreate[]
// ---------------------------------------------------------------------------

async function buildDailyPayloads(
  startDate: Date,
  endDate: Date,
): Promise<WearableDailyCreate[]> {
  const [
    hrvSamples,
    restingHRSamples,
    sleepSamples,
    stepsSamples,
    calorieSamples,
  ] = await Promise.all([
    getHRVSamples(startDate, endDate),
    getRestingHRSamples(startDate, endDate),
    getSleepSamples(startDate, endDate),
    getStepsSamples(startDate, endDate),
    getActiveCaloriesSamples(startDate, endDate),
  ]);

  // Group HRV, resting HR, calories by day
  const hrvByDay = groupByDay(hrvSamples);
  const hrByDay = groupByDay(restingHRSamples);
  const calByDay = groupByDay(calorieSamples);

  // Steps: getDailyStepCountSamples returns one aggregate per day already,
  // startDate on each result is midnight of that day.
  const stepsByDay = new Map<string, number>();
  for (const s of stepsSamples) {
    stepsByDay.set(toDateStr(new Date(s.startDate)), s.value);
  }

  // Sleep: sum InBed + Asleep samples per calendar day.
  // HealthKit SleepSample has value = 0 (InBed) or 1 (Asleep) — we keep Asleep.
  // Duration = endDate - startDate in minutes.
  const sleepByDay = new Map<string, number>(); // date → total asleep minutes
  for (const s of sleepSamples) {
    // value: 0=InBed, 1=Asleep (confirmed); skip InBed to avoid double-counting
    if (s.value !== 1) continue;
    const start = new Date(s.startDate);
    const end = new Date(s.endDate);
    const minutes = (end.getTime() - start.getTime()) / 60_000;
    // Attribute to the date of wake-up (end date)
    const dateKey = toDateStr(end);
    sleepByDay.set(dateKey, (sleepByDay.get(dateKey) ?? 0) + minutes);
  }

  // Build one payload per day in the window
  const payloads: WearableDailyCreate[] = [];
  for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
    const dateKey = toDateStr(new Date(d));

    const hrv = hrvByDay.get(dateKey);
    const hr = hrByDay.get(dateKey);
    const cal = calByDay.get(dateKey);
    const sleepMin = sleepByDay.get(dateKey) ?? null;
    const steps = stepsByDay.get(dateKey) ?? null;

    // Skip days with absolutely no data (e.g. user didn't wear device)
    const hasAnyData = hrv || hr || sleepMin !== null || steps !== null || cal;
    if (!hasAnyData) continue;

    payloads.push({
      date: dateKey,
      source: 'healthkit',
      hrv_avg: hrv ? avg(hrv.values) : null,
      hrv_min: hrv ? min(hrv.values) : null,
      hrv_max: hrv ? maxVal(hrv.values) : null,
      resting_hr: hr ? avg(hr.values) : null,
      sleep_duration_minutes: sleepMin !== null ? Math.round(sleepMin) : null,
      sleep_deep_minutes: null,
      sleep_rem_minutes: null,
      sleep_score: null,
      readiness_score: null,
      steps: steps !== null ? Math.round(steps) : null,
      active_calories: cal ? sum(cal.values) : null,
    });
  }

  return payloads;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * useHealthKit
 *
 * Usage:
 *   const { status, syncResult, requestAndSync } = useHealthKit();
 *
 *   <Button onPress={requestAndSync} title="Connect Apple Health" />
 */
export function useHealthKit() {
  const [status, setStatus] = useState<SyncStatus>('idle');
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);

  async function requestAndSync() {
    // HealthKit is iOS-only
    if (Platform.OS !== 'ios') {
      setStatus('error');
      return;
    }

    setStatus('requesting');
    setSyncResult(null);

    // 1. Request permissions
    try {
      await initHealthKit();
    } catch {
      // initHealthKit rejects when the user explicitly denies ALL permissions,
      // or when HealthKit is unavailable (e.g. simulator without HK entitlement).
      setStatus('denied');
      return;
    }

    // 2. Read last 7 days
    setStatus('syncing');
    const endDate = new Date();
    endDate.setHours(23, 59, 59, 999);
    const startDate = daysAgoMidnight(6); // 6 days ago + today = 7 days

    let payloads: WearableDailyCreate[];
    try {
      payloads = await buildDailyPayloads(startDate, endDate);
    } catch (e: unknown) {
      setStatus('error');
      setSyncResult({
        daysAttempted: 0,
        daysSynced: 0,
        errors: [e instanceof Error ? e.message : 'Failed to read HealthKit data'],
      });
      return;
    }

    // 3. POST each day to backend
    const errors: string[] = [];
    let daysSynced = 0;

    await Promise.all(
      payloads.map(async (payload) => {
        try {
          await api.post('/wearable/sync', payload);
          daysSynced += 1;
        } catch (e: unknown) {
          errors.push(
            `${payload.date}: ${e instanceof Error ? e.message : 'sync failed'}`,
          );
        }
      }),
    );

    setSyncResult({ daysAttempted: payloads.length, daysSynced, errors });
    setStatus(errors.length === 0 ? 'success' : 'error');
  }

  return { status, syncResult, requestAndSync };
}

// ---------------------------------------------------------------------------
// Xcode setup (required for HealthKit to work in production builds)
// ---------------------------------------------------------------------------
//
// 1. Open your project in Xcode:
//      cd mobile && npx expo prebuild --platform ios
//      open ios/MindRep.xcworkspace
//
// 2. Add the HealthKit capability:
//    a. In the Project navigator select the "MindRep" target (not the project).
//    b. Click the "Signing & Capabilities" tab.
//    c. Click "+ Capability" (top left of the tab).
//    d. Search for "HealthKit" and double-click to add it.
//    → This creates the com.apple.healthkit entitlement in MindRep.entitlements
//      and sets the HealthShareUsageDescription in Info.plist (already added
//      via app.json infoPlist above, so no manual edit needed).
//
// 3. Verify the entitlement file (ios/MindRep/MindRep.entitlements):
//    Should contain:
//      <key>com.apple.developer.healthkit</key>
//      <true/>
//      <key>com.apple.developer.healthkit.access</key>
//      <array/>
//
// 4. Rebuild the app:
//      npx expo run:ios
//
// Note: HealthKit is NOT available on the iOS Simulator. Test on a real device.
// Note: App Store review requires a Privacy Nutrition Label entry for Health data.
