import { useState } from 'react';

const EVENT_CONFIG = {
  orchestrator_start:     { label: 'Orchestrator',     color: '#4338CA', bg: '#EEF2FF', border: '#C7D2FE', icon: '⬡' },
  orchestrator_route:     { label: 'Orchestrator',     color: '#4338CA', bg: '#EEF2FF', border: '#C7D2FE', icon: '→' },
  advisor_start:          { label: 'Advisor Agent',    color: '#92400E', bg: '#FFFBEB', border: '#FDE68A', icon: '📚' },
  advisor_source:         { label: 'Knowledge Source', color: '#92400E', bg: '#FFFBEB', border: '#FDE68A', icon: '🔍' },
  advisor_result:         { label: 'Advisor Result',   color: '#15803D', bg: '#F0FDF4', border: '#BBF7D0', icon: '✓' },
  handoff:                { label: 'Agent Handoff',    color: '#6D28D9', bg: '#F5F3FF', border: '#DDD6FE', icon: '⇄' },
  action_start:           { label: 'Action Agent',     color: '#1E40AF', bg: '#EFF6FF', border: '#BFDBFE', icon: '⚙️' },
  action_tool_call:       { label: 'MCP Tool Call',    color: '#1E40AF', bg: '#EFF6FF', border: '#BFDBFE', icon: '🔧' },
  action_tool_result:     { label: 'Tool Result',      color: '#15803D', bg: '#F0FDF4', border: '#BBF7D0', icon: '✓' },
  orchestrator_synthesize:{ label: 'Orchestrator',     color: '#4338CA', bg: '#EEF2FF', border: '#C7D2FE', icon: '⬡' },
  complete:               { label: 'Complete',         color: '#15803D', bg: '#F0FDF4', border: '#BBF7D0', icon: '✓' },
  error:                  { label: 'Error',            color: '#B91C1C', bg: '#FEF2F2', border: '#FECACA', icon: '✗' },
};

const FALLBACK = { label: 'Event', color: '#4338CA', bg: '#EEF2FF', border: '#C7D2FE', icon: '•' };

export default function FlowEvent({ event, isLatest, isPulsing }) {
  const [expanded, setExpanded] = useState(false);
  const cfg      = EVENT_CONFIG[event.type] || FALLBACK;
  const hasInputs = event.inputs && Object.keys(event.inputs).length > 0;
  const hasDetail = Boolean(event.detail);

  return (
    <div
      className="flow-event"
      style={{
        display: 'flex',
        gap: '10px',
        padding: '10px 12px',
        borderRadius: '8px',
        border: `1px solid ${cfg.border}`,
        background: cfg.bg,
      }}
    >
      {/* Icon */}
      <div
        className="flex items-center justify-center flex-shrink-0"
        style={{ width: '22px', height: '22px', fontSize: '13px', marginTop: '1px' }}
      >
        {cfg.icon}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Label row */}
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="text-xs font-bold uppercase"
            style={{ color: cfg.color, letterSpacing: '0.07em' }}
          >
            {cfg.label}
          </span>
          {isPulsing && isLatest && (
            <span className="flex items-center gap-0.5">
              {[0, 1, 2].map(i => (
                <span
                  key={i}
                  style={{
                    width: '4px', height: '4px', borderRadius: '50%',
                    background: cfg.color, opacity: 0.7, display: 'inline-block',
                    animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
                  }}
                />
              ))}
            </span>
          )}
        </div>

        {/* Message */}
        <div className="text-sm font-medium mt-0.5" style={{ color: '#1F2937' }}>
          {event.type === 'advisor_source' ? (
            <span>
              Querying:{' '}
              <code
                className="text-xs px-1.5 py-px rounded"
                style={{ background: '#FEF3C7', color: '#92400E', fontFamily: 'monospace' }}
              >
                {event.message}
              </code>
            </span>
          ) : event.type === 'action_tool_call' ? (
            <span>
              Tool:{' '}
              <code
                className="text-xs px-1.5 py-px rounded"
                style={{ background: '#DBEAFE', color: '#1E40AF', fontFamily: 'monospace' }}
              >
                {event.message}
              </code>
              {hasInputs && (
                <button
                  onClick={() => setExpanded(e => !e)}
                  className="bg-transparent border-none p-0 cursor-pointer underline text-xs ml-2"
                  style={{ color: '#1E40AF', fontFamily: 'inherit' }}
                >
                  {expanded ? 'hide inputs ▲' : 'show inputs ▼'}
                </button>
              )}
            </span>
          ) : (
            event.message
          )}
        </div>

        {/* Expandable inputs */}
        {expanded && hasInputs && (
          <div
            className="mt-2 p-2 rounded text-xs"
            style={{
              background: '#F0F9FF', border: '1px solid #BAE6FD',
              fontFamily: 'monospace', color: '#0C4A6E',
            }}
          >
            {Object.entries(event.inputs).map(([k, v]) => (
              <div key={k}>
                <span style={{ opacity: 0.6 }}>{k}:</span> {v}
              </div>
            ))}
          </div>
        )}

        {/* Detail */}
        {hasDetail && (
          <div className="text-xs mt-0.5" style={{ color: '#6B7280' }}>
            {event.detail}
          </div>
        )}
      </div>
    </div>
  );
}
