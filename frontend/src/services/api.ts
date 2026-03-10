import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_BASE = API_URL.replace(/\/+$/, '');

export const api = axios.create({
  baseURL: API_URL,
});

export type AgentEvent =
  | { type: 'thought'; content: string }
  | { type: 'action'; tool: string }
  | { type: 'observation'; summary: string }
  | { type: 'insight_token'; token: string }
  | { type: 'session_title'; title: string }
  | { type: 'done' }
  | { type: 'error'; message: string };

export interface SessionSummary {
  session_id: string;
  title: string;
}

export interface HistoryItem {
  role: 'user' | 'assistant';
  content: string;
}

export async function streamAnalysis(
  question: string,
  file: File | undefined,
  model: string,
  sessionId: string,
  onEvent: (event: AgentEvent) => void
) {
  const formData = new FormData();
  formData.append('question', question);
  formData.append('model', model);
  formData.append('session_id', sessionId);
  if (file) formData.append('file', file);

  const response = await fetch(`${API_BASE}/stream`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
  if (!response.body) throw new Error('No response body');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const dispatchEventBlock = (block: string) => {
    const dataLines = block
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim());

    if (dataLines.length === 0) return;

    const payload = dataLines.join('');
    if (!payload) return;

    try {
      const event = JSON.parse(payload) as AgentEvent;
      onEvent(event);
    } catch {
      // Ignorar bloques incompletos o corruptos
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() ?? '';

    for (const block of blocks) {
      dispatchEventBlock(block);
    }

    if (done) break;
  }

  if (buffer.trim()) {
    dispatchEventBlock(buffer);
  }
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const response = await api.get<SessionSummary[]>('/sessions');
  return response.data;
}

export async function fetchSessionHistory(sessionId: string): Promise<HistoryItem[]> {
  const response = await api.get<HistoryItem[]>(`/history/${encodeURIComponent(sessionId)}`);
  return response.data;
}

export async function renameSession(sessionId: string, title: string): Promise<void> {
  await api.patch(`/sessions/${encodeURIComponent(sessionId)}/rename`, { title });
}

export async function deleteSession(sessionId: string): Promise<void> {
  await api.delete(`/sessions/${encodeURIComponent(sessionId)}`);
}
