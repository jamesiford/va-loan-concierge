import { useRef, useEffect } from 'react';
import ChatMessage from './ChatMessage';

const DEMO_QUERIES = [
  { label: 'IRRRL Eligibility',    query: 'Am I eligible for an IRRRL refinance?' },
  { label: 'VA Funding Fee',       query: 'Am I exempt from the VA funding fee, and how is it calculated?' },
  { label: 'Reuse VA Benefit',     query: 'Can I use my VA loan benefit a second time?' },
  { label: 'Refi + Book Call ★',   query: "I'm thinking about refinancing — am I eligible for an IRRRL, and can you show me what I'd save and schedule a call for Thursday?" },
  { label: 'Weekly Market Digest', query: 'Send me the weekly VA mortgage market intelligence digest.' },
];

export default function ChatPanel({ messages, isStreaming, onSend }) {
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="flex flex-col flex-1 overflow-hidden min-h-0">
      {/* Demo query buttons */}
      <div
        className="flex items-center gap-2 flex-wrap px-4 py-2.5 flex-shrink-0"
        style={{ borderBottom: '1px solid #E5E2DC', background: '#FFFFFF' }}
      >
        <span
          className="text-xs font-semibold uppercase flex-shrink-0"
          style={{ color: '#6B7280', letterSpacing: '0.05em' }}
        >
          Try:
        </span>
        {DEMO_QUERIES.map(dq => (
          <button
            key={dq.label}
            className="demo-btn text-xs font-medium px-3 py-1 rounded-full transition-all"
            style={{
              border: '1px solid #E5E2DC',
              background: 'white',
              color: '#374151',
              opacity: isStreaming ? 0.5 : 1,
              cursor: isStreaming ? 'not-allowed' : 'pointer',
              fontFamily: 'inherit',
            }}
            onClick={() => onSend(dq.query)}
            disabled={isStreaming}
          >
            {dq.label}
          </button>
        ))}
      </div>

      {/* Messages scroll area */}
      <div className="flex-1 overflow-y-auto px-4 py-5" style={{ background: '#F8F7F4' }}>
        {messages.map((msg, i) => (
          <ChatMessage key={i} message={msg} />
        ))}

        {/* Thinking indicator */}
        {isStreaming && (
          <div className="flex items-start gap-2 mb-4">
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0"
              style={{ background: '#002244' }}
            >
              🏠
            </div>
            <div
              className="flex items-center gap-1 px-4 py-3 shadow-sm"
              style={{
                borderRadius: '4px 18px 18px 18px',
                background: '#FFFFFF',
                border: '1px solid #E5E2DC',
              }}
            >
              {[0, 1, 2].map(i => (
                <div
                  key={i}
                  style={{
                    width: '6px', height: '6px', borderRadius: '50%',
                    background: '#9CA3AF',
                    animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
                  }}
                />
              ))}
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>
    </div>
  );
}
