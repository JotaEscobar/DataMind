import { create } from 'zustand';
import { v4 as uuidv4 } from 'uuid';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  thoughts?: string[];
  action?: string;
  isStreaming?: boolean;
}

interface ChatState {
  sessionId: string;
  messages: Message[];
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
  setSessionId: (sessionId: string) => void;
  setMessagesFromHistory: (messages: Array<Pick<Message, 'role' | 'content'>>) => void;
  addMessage: (message: Omit<Message, 'id'>) => void;
  updateLastMessage: (
    update: Partial<Message> | ((msg: Message) => Partial<Message> | Message)
  ) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  sessionId: uuidv4(),
  messages: [],
  isLoading: false,
  setIsLoading: (loading) => set({ isLoading: loading }),
  setSessionId: (sessionId) => set({ sessionId }),
  setMessagesFromHistory: (messages) => set({
    messages: messages.map((message) => ({
      ...message,
      id: uuidv4(),
    })),
  }),
  addMessage: (message) => set((state) => ({
    messages: [...state.messages, { ...message, id: uuidv4() }]
  })),
  updateLastMessage: (update) => set((state) => {
    const newMessages = [...state.messages];
    if (newMessages.length === 0) return { messages: newMessages };

    const lastIndex = newMessages.length - 1;
    if (typeof update === 'function') {
      const result = update(newMessages[lastIndex]);
      newMessages[lastIndex] = { ...newMessages[lastIndex], ...result };
    } else {
      newMessages[lastIndex] = { ...newMessages[lastIndex], ...update };
    }

    return { messages: newMessages };
  }),
  clearMessages: () => set({ messages: [], sessionId: uuidv4() }),
}));
