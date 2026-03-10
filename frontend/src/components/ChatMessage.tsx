import React from 'react';
import { cn } from '../lib/utils';
import type { Message } from '../store/useChatStore';
import { ThoughtProcess } from './ThoughtProcess';

interface ChatMessageProps {
  message: Message;
}

function renderMarkdown(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

export const ChatMessage: React.FC<ChatMessageProps> = ({ message }) => {
  const isUser = message.role === 'user';
  const time = new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });

  return (
    <div className={cn('msg-row', isUser ? 'user' : 'assistant')}>
      <div className="msg-meta-row">
        {!isUser && <div className="msg-dot" />}
        <span className="msg-sender">{isUser ? 'TÚ' : 'DATAMIND AI'}</span>
        <span className="msg-time">{time}</span>
      </div>

      {!isUser && message.thoughts && message.thoughts.length > 0 && (
        <ThoughtProcess
          thoughts={message.thoughts as string[]}
          action={message.action}
          isStreaming={message.isStreaming}
        />
      )}

      {isUser ? (
        <div className="user-bubble">{message.content}</div>
      ) : (
        <>
          <div
            className="assistant-content"
            dangerouslySetInnerHTML={{
              __html: message.content
                ? renderMarkdown(message.content)
                : message.isStreaming
                  ? '<span style="display: flex; align-items: center; gap: 8px; color: var(--text-mid); font-size: 13px; font-style: italic;">Procesando <span class="streaming-dots"><span></span><span></span><span></span></span></span>'
                  : ''
            }}
          />

          {/* ── Gráficos PNG generados por código ── */}
          {message.chartImages && message.chartImages.length > 0 && (
            <div className="chart-images-wrapper" style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              marginTop: '12px',
            }}>
              {message.chartImages.map((img, idx) => (
                <div key={idx} style={{
                  borderRadius: '10px',
                  overflow: 'hidden',
                  border: '1px solid var(--border, #1a2d42)',
                  background: '#111d2e',
                }}>
                  <img
                    src={`data:image/png;base64,${img}`}
                    alt={`Gráfico ${idx + 1}`}
                    style={{
                      width: '100%',
                      maxWidth: '720px',
                      display: 'block',
                      borderRadius: '9px',
                    }}
                  />
                  <div style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    padding: '6px 10px',
                    borderTop: '1px solid var(--border, #1a2d42)',
                  }}>
                    <a
                      href={`data:image/png;base64,${img}`}
                      download={`datamind-grafico-${idx + 1}.png`}
                      style={{
                        fontSize: '11px',
                        color: 'var(--accent, #00d4ff)',
                        textDecoration: 'none',
                        opacity: 0.8,
                      }}
                    >
                      ↓ Descargar PNG
                    </a>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};