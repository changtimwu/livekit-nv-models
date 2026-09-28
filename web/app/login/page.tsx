'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { SITE } from '@/lib/site';

export default function LoginPage() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      if (res.ok) {
        window.location.href = '/';
        return;
      }
      const data = await res.json().catch(() => ({}));
      setError(data.error ?? 'Login failed.');
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid h-svh place-content-center px-6">
      <form onSubmit={onSubmit} className="flex w-72 flex-col items-center gap-4 text-center">
        <h1 className="text-foreground text-lg font-semibold">{SITE.title}</h1>
        <p className="text-muted-foreground text-sm">{SITE.loginPrompt}</p>
        <input
          type="password"
          autoFocus
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          aria-label="Password"
          className="border-input bg-background text-foreground focus-visible:ring-ring w-full rounded-full border px-4 py-2 text-sm outline-none focus-visible:ring-2"
        />
        <Button
          type="submit"
          size="lg"
          disabled={busy || !password}
          className="w-full rounded-full font-mono text-xs font-bold tracking-wider uppercase"
        >
          {busy ? 'Checking…' : 'Enter'}
        </Button>
        {error && <p className="text-destructive text-sm">{error}</p>}
      </form>
    </main>
  );
}
