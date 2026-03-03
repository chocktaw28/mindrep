import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { signInWithMagicLink } from '@/services/auth';

const TINT = '#2f95dc';

type Status = 'idle' | 'loading' | 'success' | 'error';

export default function LoginScreen() {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [errorMessage, setErrorMessage] = useState('');

  async function handleSendLink() {
    const trimmed = email.trim();
    if (!trimmed) {
      setStatus('error');
      setErrorMessage('Please enter your email address.');
      return;
    }

    setStatus('loading');
    setErrorMessage('');

    try {
      await signInWithMagicLink(trimmed);
      setStatus('success');
    } catch (err: unknown) {
      setStatus('error');
      setErrorMessage(
        err instanceof Error ? err.message : 'Something went wrong. Please try again.'
      );
    }
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.flex}
    >
      <View style={styles.container}>
        <View style={styles.top}>
          <Text style={styles.wordmark}>MindRep</Text>
          <Text style={styles.tagline}>Exercise for your mind.</Text>
        </View>

        <View style={styles.card}>
          {status === 'success' ? (
            <View style={styles.successBlock}>
              <Text style={styles.successHeading}>Check your email</Text>
              <Text style={styles.successBody}>
                We sent a login link to {email.trim()}. Open it to sign in.
              </Text>
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => {
                  setStatus('idle');
                  setEmail('');
                }}
                activeOpacity={0.7}
              >
                <Text style={styles.secondaryButtonText}>Use a different email</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <>
              <Text style={styles.label}>Email address</Text>
              <TextInput
                style={styles.input}
                placeholder="you@example.com"
                placeholderTextColor="#AAAAAA"
                value={email}
                onChangeText={text => {
                  setEmail(text);
                  if (status === 'error') setStatus('idle');
                }}
                keyboardType="email-address"
                autoCapitalize="none"
                autoCorrect={false}
                autoComplete="email"
                editable={status !== 'loading'}
                returnKeyType="send"
                onSubmitEditing={handleSendLink}
              />

              <TouchableOpacity
                style={[styles.button, status === 'loading' && styles.buttonDisabled]}
                onPress={handleSendLink}
                disabled={status === 'loading'}
                activeOpacity={0.8}
              >
                {status === 'loading' ? (
                  <ActivityIndicator color="#FFFFFF" />
                ) : (
                  <Text style={styles.buttonText}>Send magic link</Text>
                )}
              </TouchableOpacity>

              {status === 'error' && errorMessage ? (
                <View style={styles.errorBox}>
                  <Text style={styles.errorText}>{errorMessage}</Text>
                </View>
              ) : null}
            </>
          )}
        </View>

        <Text style={styles.disclaimer}>
          MindRep is a wellness tool, not a medical device.
        </Text>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  container: {
    flex: 1,
    paddingHorizontal: 28,
    justifyContent: 'center',
  },
  top: {
    alignItems: 'center',
    marginBottom: 48,
  },
  wordmark: {
    fontSize: 32,
    fontWeight: '700',
    color: '#1A1A1A',
    letterSpacing: -0.8,
  },
  tagline: {
    marginTop: 6,
    fontSize: 15,
    color: '#888888',
  },
  card: {
    backgroundColor: '#F8F8F8',
    borderRadius: 16,
    padding: 24,
    borderWidth: 1,
    borderColor: '#EEEEEE',
  },
  label: {
    fontSize: 13,
    fontWeight: '600',
    color: '#888888',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    marginBottom: 10,
  },
  input: {
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#E8E8E8',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
    color: '#1A1A1A',
    marginBottom: 16,
  },
  button: {
    backgroundColor: TINT,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
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
    marginTop: 14,
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
  successBlock: {
    alignItems: 'center',
  },
  successHeading: {
    fontSize: 20,
    fontWeight: '700',
    color: '#1A1A1A',
    marginBottom: 10,
  },
  successBody: {
    fontSize: 15,
    color: '#666666',
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 24,
  },
  secondaryButton: {
    paddingVertical: 10,
  },
  secondaryButtonText: {
    fontSize: 15,
    color: TINT,
    fontWeight: '500',
  },
  disclaimer: {
    marginTop: 32,
    fontSize: 12,
    color: '#CCCCCC',
    textAlign: 'center',
  },
});
