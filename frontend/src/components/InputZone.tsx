import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Send, Paperclip, X, ChevronDown, Loader2 } from 'lucide-react';
import { cn } from '../lib/utils';

interface InputZoneProps {
  onSendMessage: (msg: string, file?: File) => void;
  isLoading: boolean;
  currentModel: string;
  onModelChange: (model: string) => void;
}

export const InputZone: React.FC<InputZoneProps> = ({
  onSendMessage,
  isLoading,
  currentModel,
  onModelChange,
}) => {
  const [input, setInput] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);

  const modelMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const models = [
    { id: 'groq/llama-3.3-70b-versatile', label: 'Groq Llama 3.3', desc: 'Última generación · Reasoning', provider: 'groq' },
    { id: 'groq/mixtral-8x7b-32768', label: 'Groq Mixtral', desc: 'Eficiente · Código y datos', provider: 'groq' },
    { id: 'llama3.1', label: 'Ollama Llama 3.1', desc: 'Local · Sin internet', provider: 'ollama' },
    { id: 'deepseek-r1:8b', label: 'Ollama DeepSeek R1', desc: 'Local · Razonamiento', provider: 'ollama' },
  ];

  const currentLabel = models.find(m => m.id === currentModel)?.label ?? 'Groq Llama 3.1';
  const hasContent = Boolean(input.trim() || file);

  const fileMeta = useMemo(() => {
    if (!file) return null;
    const ext = file.name.split('.').pop()?.toUpperCase() ?? 'FILE';
    const kb = file.size / 1024;
    const size = kb > 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(kb))} KB`;
    return { ext, size };
  }, [file]);

  useEffect(() => {
    const onOutside = (e: MouseEvent) => {
      if (!modelMenuRef.current?.contains(e.target as Node)) setModelMenuOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setModelMenuOpen(false); };
    document.addEventListener('mousedown', onOutside);
    document.addEventListener('keydown', onEsc);
    return () => { document.removeEventListener('mousedown', onOutside); document.removeEventListener('keydown', onEsc); };
  }, []);

  const handleSend = () => {
    if (!hasContent || isLoading) return;
    onSendMessage(input, file ?? undefined);
    setInput('');
    setFile(null);
    setModelMenuOpen(false);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const autoResize = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
    }
  };

  return (
    <div className="input-zone">
      <div className="input-pill">

        {/* ── Selector de modelo ── */}
        <div className="model-picker" ref={modelMenuRef}>
          <button
            type="button"
            onClick={() => setModelMenuOpen(p => !p)}
            className={cn('model-capsule', modelMenuOpen && 'open')}
          >
            <span className="name">{currentLabel}</span>
            <ChevronDown size={10} strokeWidth={3} className={cn('chevron', modelMenuOpen && 'rotate-180')} />
          </button>

          {modelMenuOpen && (
            <div className="model-dropdown">
              <div className="model-dropdown-label">Modelos disponibles</div>
              {models.map(m => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => { onModelChange(m.id); setModelMenuOpen(false); }}
                  className={cn('model-opt', currentModel === m.id && 'active')}
                >
                  <span className="opt-name">{m.label}</span>
                  <span className="opt-desc">{m.desc}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* ── Adjuntar ── */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isLoading}
          className="attach-btn"
          title="Adjuntar CSV o Excel"
        >
          <Paperclip size={16} />
        </button>
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          accept=".csv,.xlsx,.xls"
          onChange={e => setFile(e.target.files?.[0] ?? null)}
        />

        {/* ── Preview archivo ── */}
        {file && fileMeta && (
          <div className="attach-preview">
            <Paperclip size={10} />
            <span className="attach-name">{file.name}</span>
            <button type="button" onClick={() => setFile(null)}><X size={11} /></button>
          </div>
        )}

        {/* ── Textarea ── */}
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          placeholder="Pregunta sobre tus datos..."
          disabled={isLoading}
          onChange={e => { setInput(e.target.value); autoResize(); }}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          className="chat-textarea"
        />

        {/* ── Enviar ── */}
        <button
          type="button"
          disabled={!hasContent || isLoading}
          onClick={handleSend}
          className="send-btn"
        >
          {isLoading
            ? <Loader2 size={14} className="animate-spin" />
            : <Send size={14} />
          }
        </button>
      </div>

      <div className="input-hint">
        Enter para enviar · Shift+Enter nueva línea · 📎 para adjuntar CSV/Excel
      </div>
    </div>
  );
};