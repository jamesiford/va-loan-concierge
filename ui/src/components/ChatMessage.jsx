export default function ChatMessage({ message }) {
  const isUser = message.role === 'user';

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
          🏠
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
          whiteSpace: 'pre-wrap',
        }}
      >
        {message.content}
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
