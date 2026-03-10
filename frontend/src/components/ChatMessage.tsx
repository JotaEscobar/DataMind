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
      )}
    </div>
  );
};