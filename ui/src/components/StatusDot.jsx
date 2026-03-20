import { useState, useEffect } from 'react';

const MOCK_MODE = import.meta.env.VITE_MOCK_MODE === 'true';

export default function StatusDot({ isStreaming }) {
  const [connected, setConnected] = useState(MOCK_MODE ? true : null);

  useEffect(() => {
    if (MOCK_MODE) return;
    let mounted = true;

    async function check() {
      try {
        const res  = await fetch('/api/health');
        const data = await res.json();
        if (mounted) setConnected(data.status === 'ok');
      } catch {
        if (mounted) setConnected(false);
      }
    }

    check();
    const interval = setInterval(check, 15_000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  let dotColor, label;
  if (isStreaming) {
    dotColor = '#F59E0B';
    label    = 'Processing...';
  } else if (connected === false) {
    dotColor = '#6B7280';
    label    = 'Offline';
  } else {
    dotColor = '#22C55E';
    label    = 'Ready';
  }

  return (
    <div className="flex items-center gap-1.5">
      <div
        style={{
          width: '8px', height: '8px', borderRadius: '50%',
          background: dotColor,
          boxShadow: `0 0 6px ${dotColor}`,
          animation: isStreaming ? 'pulse 1s ease-in-out infinite' : 'none',
        }}
      />
      <span className="text-xs" style={{ color: '#93A8C0' }}>{label}</span>
    </div>
  );
}
