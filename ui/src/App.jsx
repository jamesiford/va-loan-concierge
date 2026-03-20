import { useState } from 'react';
import { useAgentStream } from './hooks/useAgentStream';
import ChatPanel      from './components/ChatPanel';
import ChatInput      from './components/ChatInput';
import AgentFlowLog   from './components/AgentFlowLog';
import StatusDot      from './components/StatusDot';
import BorrowerProfile from './components/BorrowerProfile';

export default function App() {
  const { messages, flowEvents, isStreaming, sendQuery, clearEvents } = useAgentStream();
  const [logVisible, setLogVisible] = useState(true);
  const [profileId, setProfileId] = useState(null);

  const handleSend = (query) => sendQuery(query, profileId);

  return (
    <div className="flex flex-col h-screen overflow-hidden">

      {/* ── Header ── */}
      <header
        className="flex items-center justify-between px-6 flex-shrink-0 shadow-md"
        style={{ height: '56px', background: '#002244' }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center text-base flex-shrink-0"
            style={{ background: '#C8102E' }}
          >
            🏠
          </div>
          <div>
            <div
              className="text-white text-base"
              style={{ fontFamily: "'Poppins', sans-serif", fontWeight: 400, letterSpacing: '0.01em' }}
            >
              VA Loan Concierge
            </div>
            <div
              className="text-xs uppercase"
              style={{ color: '#93A8C0', letterSpacing: '0.06em' }}
            >
              Multi-Agent Demo · Foundry IQ &amp; Custom MCP Server
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <StatusDot isStreaming={isStreaming} />
          <button
            onClick={() => setLogVisible(v => !v)}
            className="flex items-center gap-1 text-white text-xs px-2.5 py-1 rounded-md cursor-pointer border-none"
            style={{ background: 'rgba(255,255,255,0.1)', fontFamily: 'inherit' }}
          >
            ⚡ {logVisible ? 'Hide' : 'Show'} Agent Log
          </button>
        </div>
      </header>

      {/* ── Borrower profile selector ── */}
      <BorrowerProfile profileId={profileId} onChange={setProfileId} />

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden min-h-0">

        {/* Left: Chat */}
        <div
          className="flex flex-col min-w-0 transition-all duration-300"
          style={{
            flex: logVisible ? '1 1 55%' : '1 1 100%',
            borderRight: logVisible ? '1px solid #E5E2DC' : 'none',
          }}
        >
          <ChatPanel messages={messages} isStreaming={isStreaming} onSend={handleSend} />
          <ChatInput onSend={handleSend} disabled={isStreaming} />
        </div>

        {/* Right: Agent Flow Log */}
        {logVisible && (
          <AgentFlowLog events={flowEvents} isStreaming={isStreaming} onClear={clearEvents} />
        )}
      </div>
    </div>
  );
}
