/**
 * Lightweight markdown-to-HTML for assistant messages.
 *
 * Handles: **bold**, *italic*, `code`, - lists, numbered lists,
 * headings (## / ###), and paragraphs.
 */
function renderMarkdown(text) {
  return text
    .replace(/</g, '&lt;')
    // Headings
    .replace(/^### (.+)$/gm, '<h4 class="font-semibold text-sm mt-3 mb-1">$1</h4>')
    .replace(/^## (.+)$/gm, '<h3 class="font-semibold text-base mt-3 mb-1">$1</h3>')
    // Bold + italic
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code class="bg-gray-100 px-1 rounded text-xs">$1</code>')
    // Unordered lists
    .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc">$1</li>')
    // Numbered lists
    .replace(/^\d+\. (.+)$/gm, '<li class="ml-4 list-decimal">$1</li>')
    // Paragraphs — double newlines
    .replace(/\n\n/g, '<br/><br/>')
    // Single newlines within text
    .replace(/\n/g, '<br/>');
}

const AGENT_ICONS = {
  advisor: '📚',
  calculator: '🧮',
  scheduler: '📅',
  calendar: '📆',
};

const AGENT_COLORS = {
  advisor: '#92400E',
  calculator: '#1E40AF',
  scheduler: '#0E7490',
  calendar: '#BE185D',
};

export default function ChatMessage({ message }) {
  const isUser = message.role === 'user';
  const isHandoff = message.role === 'handoff';
  const isPlan = message.role === 'plan';

  // ── Plan / handoff indicator ────────────────────────────────────
  if (isPlan || isHandoff) {
    return (
      <div
        className="flex items-center justify-center gap-2 my-3"
        style={{ color: '#9CA3AF' }}
      >
        <div style={{ height: '1px', flex: 1, background: '#E5E7EB' }} />
        <span className="text-xs font-medium uppercase" style={{ letterSpacing: '0.05em' }}>
          ⇄ {message.content}
        </span>
        <div style={{ height: '1px', flex: 1, background: '#E5E7EB' }} />
      </div>
    );
  }

  // ── User / assistant messages ──────────────────────────────────
  const agent = message.agent;
  const label = message.label;
  const icon = (agent && AGENT_ICONS[agent]) || '🏠';
  const labelColor = (agent && AGENT_COLORS[agent]) || '#6B7280';

  return (
    <div
      className="flex mb-4"
      style={{ justifyContent: isUser ? 'flex-end' : 'flex-start' }}
    >
      {!isUser && (
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0 mr-2.5"
          style={{ background: '#002244', marginTop: '2px' }}
        >
          {icon}
        </div>
      )}

      <div
        className="text-sm leading-relaxed shadow-sm"
        style={{
          maxWidth: '80%',
          padding: '12px 16px',
          borderRadius: isUser ? '18px 18px 4px 18px' : '4px 18px 18px 18px',
          background: isUser ? '#002244' : '#FFFFFF',
          color: isUser ? '#FFFFFF' : '#1F2937',
          border: isUser ? 'none' : '1px solid #E5E2DC',
        }}
      >
        {!isUser && label && (
          <div
            className="text-xs font-semibold mb-1.5"
            style={{ color: labelColor }}
          >
            {label}
          </div>
        )}
        {isUser ? (
          <span style={{ whiteSpace: 'pre-wrap' }}>{message.content}</span>
        ) : (
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
        )}
      </div>

      {isUser && (
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0 ml-2.5"
          style={{ background: '#E5E7EB', marginTop: '2px' }}
        >
          🎖️
        </div>
      )}
    </div>
  );
}
