'use client';

import { useMemo, useState } from 'react';
import { TokenSource } from 'livekit-client';
import { useSession } from '@livekit/components-react';
import { WarningIcon } from '@phosphor-icons/react/dist/ssr';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { OrderPanel } from '@/components/app/order-panel';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/ui/sonner';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { useDebugMode } from '@/hooks/useDebug';
import { SITE } from '@/lib/site';

const IN_DEVELOPMENT = process.env.NODE_ENV !== 'production';

function AppSetup() {
  useDebugMode({ enabled: IN_DEVELOPMENT });
  useAgentErrors();

  return null;
}

interface AppProps {
  tokenServerId?: string;
  tokenEndpoint: string;
  agentName?: string;
  isVideoInputSupported: boolean;
  tagline?: string;
}

export function App({
  tokenServerId,
  tokenEndpoint,
  agentName,
  isVideoInputSupported,
  tagline,
}: AppProps) {
  const tokenSource = useMemo(
    () =>
      tokenServerId
        ? TokenSource.developmentTokenServer(tokenServerId)
        : TokenSource.endpoint(tokenEndpoint),
    [tokenServerId, tokenEndpoint]
  );

  // The picked store travels as dispatch metadata; the token endpoint validates it (#22).
  const [store, setStore] = useState(SITE.stores[0]?.slug ?? '');
  const sessionOptions = useMemo(() => {
    const opts: { agentName?: string; agentMetadata?: string } = {};
    if (agentName) opts.agentName = agentName;
    if (store) opts.agentMetadata = JSON.stringify({ store });
    return Object.keys(opts).length ? opts : undefined;
  }, [agentName, store]);
  const session = useSession(tokenSource, sessionOptions);

  return (
    <AgentSessionProvider session={session}>
      <AppSetup />
      <main className="grid h-svh grid-cols-1 place-content-center">
        <ViewController
          isVideoInputSupported={isVideoInputSupported}
          tagline={tagline}
          store={store}
          onStoreChange={setStore}
        />
      </main>
      {SITE.orderPanel && <OrderPanel />}
      <StartAudioButton label="Start Audio" />
      <Toaster
        icons={{
          warning: <WarningIcon weight="bold" />,
        }}
        position="top-center"
        className="toaster group"
        style={
          {
            '--normal-bg': 'var(--popover)',
            '--normal-text': 'var(--popover-foreground)',
            '--normal-border': 'var(--border)',
          } as React.CSSProperties
        }
      />
    </AgentSessionProvider>
  );
}
