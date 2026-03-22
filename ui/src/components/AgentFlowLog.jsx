import { useRef, useEffect } from 'react';
import FlowEvent from './FlowEvent';

const LEGEND = [
  { label: 'Orchestrator',    color: '#002244' },
  { label: 'Advisor Agent',   color: '#92400E' },
  { label: 'Calculator Agent', color: '#1E40AF' },
  { label: 'Scheduler Agent',  color: '#0E7490' },
  { label: 'Calendar Agent',   color: '#BE185D' },
];

const FOOTER_BADGES = [
  { label: 'FOUNDRY IQ', bg: '#EEF2FF', color: '#4338CA', border: '#C7D2FE' },
  { label: 'MCP',        bg: '#EFF6FF', color: '#1E40AF', border: '#BFDBFE' },
  { label: 'AZURE',      bg: '#F3F4F6', color: '#374151', border: '#E5E7EB' },
];

export default function AgentFlowLog({ events, isStreaming, onClear }) {
  const logEndRef = useRef(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  return (
    <div
      className="flex flex-col overflow-hidden flex-shrink-0"
      style={{ width: '380px', background: '#FAFAFA' }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 flex-shrink-0"
        style={{ borderBottom: '1px solid #E5E2DC', background: '#FFFFFF' }}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold" style={{ color: '#374151' }}>
            ⚡ Agent Flow Log
          </span>
          {events.length > 0 && (
            <span
              className="text-xs font-semibold px-2 py-0.5 rounded-full"
              style={{ background: '#EEF2FF', color: '#4338CA', border: '1px solid #C7D2FE' }}
            >
              {events.length} events
            </span>
          )}
        </div>
        {events.length > 0 && (
          <button
            onClick={onClear}
            className="text-xs bg-transparent border-none cursor-pointer px-1.5 py-0.5 rounded"
            style={{ color: '#6B7280', fontFamily: 'inherit' }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Legend */}
      <div
        className="flex items-center gap-3 flex-wrap px-4 py-2 flex-shrink-0"
        style={{ borderBottom: '1px solid #E5E2DC', background: '#FFFFFF' }}
      >
        {LEGEND.map(l => (
          <div key={l.label} className="flex items-center gap-1">
            <div style={{ width: '8px', height: '8px', borderRadius: '2px', background: l.color }} />
            <span className="text-xs font-medium" style={{ color: '#6B7280' }}>{l.label}</span>
          </div>
        ))}
      </div>

      {/* Events */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
        {events.length === 0 ? (
          <div
            className="flex-1 flex flex-col items-center justify-center text-center p-10 gap-3"
            style={{ color: '#6B7280' }}
          >
            <div className="text-4xl" style={{ opacity: 0.4 }}>⬡</div>
            <div className="text-sm font-medium">Agent flow will appear here</div>
            <div className="text-xs" style={{ opacity: 0.7 }}>
              Submit a query to see how the orchestrator routes your request between agents
            </div>
          </div>
        ) : (
          events.map((evt, i) => (
            <FlowEvent
              key={evt.id}
              event={evt}
              isLatest={i === events.length - 1}
              isPulsing={isStreaming}
            />
          ))
        )}
        <div ref={logEndRef} />
      </div>

      {/* Footer */}
      <div
        className="flex items-center justify-between px-4 py-2.5 flex-shrink-0"
        style={{ borderTop: '1px solid #E5E2DC', background: '#FFFFFF' }}
      >
        <span className="text-xs" style={{ color: '#6B7280' }}>Powered by</span>
        <div className="flex items-center gap-2">
          {FOOTER_BADGES.map(b => (
            <span
              key={b.label}
              className="text-xs font-bold px-2 py-0.5 rounded"
              style={{
                background: b.bg, color: b.color,
                border: `1px solid ${b.border}`,
                letterSpacing: '0.04em',
              }}
            >
              {b.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
