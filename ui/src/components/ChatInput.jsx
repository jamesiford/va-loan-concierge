import { useState, useRef } from 'react';

export default function ChatInput({ onSend, disabled }) {
  const [input, setInput] = useState('');
  const textareaRef = useRef(null);

  const handleSend = () => {
    const query = input.trim();
    if (!query || disabled) return;
    setInput('');
    onSend(query);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      className="flex-shrink-0 px-4 py-3"
      style={{ background: '#FFFFFF', borderTop: '1px solid #E5E2DC' }}
    >
      <div
        className="flex items-end gap-2.5 rounded-xl px-3 py-2.5 transition-colors"
        style={{ background: '#F9FAFB', border: '1.5px solid #E5E2DC' }}
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about VA loan eligibility, refinancing, benefits..."
          disabled={disabled}
          rows={2}
          className="flex-1 bg-transparent border-none text-sm overflow-y-auto"
          style={{
            color: '#1F2937',
            lineHeight: '1.5',
            maxHeight: '100px',
            fontFamily: 'inherit',
          }}
        />
        <button
          className="send-btn flex items-center justify-center gap-1.5 text-xs font-semibold text-white rounded-lg px-4 py-2 flex-shrink-0 transition-all border-none"
          onClick={handleSend}
          disabled={!input.trim() || disabled}
          style={{
            background: '#002244',
            cursor: (!input.trim() || disabled) ? 'not-allowed' : 'pointer',
            opacity: (!input.trim() || disabled) ? 0.5 : 1,
            fontFamily: 'inherit',
          }}
        >
          {disabled ? (
            <span
              style={{
                display: 'inline-block',
                width: '14px', height: '14px',
                border: '2px solid rgba(255,255,255,0.3)',
                borderTopColor: 'white',
                borderRadius: '50%',
                animation: 'spin 0.7s linear infinite',
              }}
            />
          ) : 'Send →'}
        </button>
      </div>
      <div className="text-xs text-center mt-1.5" style={{ color: '#6B7280' }}>
        Press Enter to send • Shift+Enter for new line
      </div>
    </div>
  );
}
