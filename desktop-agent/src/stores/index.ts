/**
 * Garage Meeting Copilot — Zustand State Stores
 * Central state management for the overlay frontend.
 */
import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TranscriptChunk {
  chunkId: string;
  sessionId: string;
  text: string;
  speakerLabel: string | null;
  startTime: number;
  endTime: number;
  isFinal: boolean;
  sequenceNumber: number;
}

export interface Suggestion {
  type: "question" | "clarification" | "fact" | "action" | "followup";
  content: string;
  confidence: number;
  contextExcerpt?: string;
}

export interface ActionItem {
  id?: string;
  title: string;
  description?: string;
  assignee?: string;
  dueDate?: string;
  priority: "low" | "medium" | "high" | "critical";
  status: string;
  confidenceScore: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  isStreaming?: boolean;
}

export interface CopilotSession {
  sessionId: string;
  garrageMeetingId: string;
  userId: string;
  organizationId: string;
  status: "active" | "ended" | "error";
  startedAt: number;
}

export type OverlayPanel = "transcript" | "suggestions" | "summary" | "chat" | "actions";

export type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "error"
  | "reconnecting";

// ── Session Store ─────────────────────────────────────────────────────────────

interface SessionStore {
  session: CopilotSession | null;
  connectionStatus: ConnectionStatus;
  isAudioCaptureActive: boolean;
  isMicEnabled: boolean;
  isSystemAudioEnabled: boolean;
  garageToken: string | null;
  gatewayUrl: string;

  setSession: (session: CopilotSession | null) => void;
  setConnectionStatus: (status: ConnectionStatus) => void;
  setAudioCaptureActive: (active: boolean) => void;
  setMicEnabled: (enabled: boolean) => void;
  setSystemAudioEnabled: (enabled: boolean) => void;
  setGarageToken: (token: string | null) => void;
  setGatewayUrl: (url: string) => void;
  reset: () => void;
}

export const useSessionStore = create<SessionStore>()(
  subscribeWithSelector((set) => ({
    session: null,
    connectionStatus: "disconnected",
    isAudioCaptureActive: false,
    isMicEnabled: true,
    isSystemAudioEnabled: false,
    garageToken: null,
    gatewayUrl:
      import.meta.env.VITE_GATEWAY_WS_URL ||
      "wss://copilot.garage.internal/ws/copilot",

    setSession: (session) => set({ session }),
    setConnectionStatus: (connectionStatus) => set({ connectionStatus }),
    setAudioCaptureActive: (isAudioCaptureActive) =>
      set({ isAudioCaptureActive }),
    setMicEnabled: (isMicEnabled) => set({ isMicEnabled }),
    setSystemAudioEnabled: (isSystemAudioEnabled) =>
      set({ isSystemAudioEnabled }),
    setGarageToken: (garageToken) => set({ garageToken }),
    setGatewayUrl: (gatewayUrl) => set({ gatewayUrl }),
    reset: () =>
      set({
        session: null,
        connectionStatus: "disconnected",
        isAudioCaptureActive: false,
      }),
  }))
);

// ── Transcript Store ──────────────────────────────────────────────────────────

interface TranscriptStore {
  chunks: TranscriptChunk[];
  pendingChunk: TranscriptChunk | null; // last non-final chunk
  totalChunks: number;
  isTranscribing: boolean;

  addChunk: (chunk: TranscriptChunk) => void;
  setPendingChunk: (chunk: TranscriptChunk | null) => void;
  setIsTranscribing: (active: boolean) => void;
  clearTranscript: () => void;
  getFullText: () => string;
}

export const useTranscriptStore = create<TranscriptStore>()(
  subscribeWithSelector((set, get) => ({
    chunks: [],
    pendingChunk: null,
    totalChunks: 0,
    isTranscribing: false,

    addChunk: (chunk) =>
      set((state) => {
        if (chunk.isFinal) {
          // Replace any pending chunk with final version
          const filteredChunks = state.chunks.filter(
            (c) => c.chunkId !== chunk.chunkId
          );
          return {
            chunks: [...filteredChunks, chunk].slice(-500), // Keep last 500 chunks
            pendingChunk:
              state.pendingChunk?.chunkId === chunk.chunkId
                ? null
                : state.pendingChunk,
            totalChunks: state.totalChunks + 1,
          };
        } else {
          return { pendingChunk: chunk };
        }
      }),

    setPendingChunk: (pendingChunk) => set({ pendingChunk }),
    setIsTranscribing: (isTranscribing) => set({ isTranscribing }),
    clearTranscript: () =>
      set({ chunks: [], pendingChunk: null, totalChunks: 0 }),

    getFullText: () => {
      const { chunks } = get();
      return chunks
        .filter((c) => c.isFinal)
        .map((c) => {
          const speaker = c.speakerLabel || "Speaker";
          return `${speaker}: ${c.text}`;
        })
        .join("\n");
    },
  }))
);

// ── Suggestions Store ─────────────────────────────────────────────────────────

interface SuggestionsStore {
  suggestions: Suggestion[];
  lastUpdated: number | null;
  isGenerating: boolean;

  setSuggestions: (suggestions: Suggestion[]) => void;
  setIsGenerating: (generating: boolean) => void;
  clearSuggestions: () => void;
}

export const useSuggestionsStore = create<SuggestionsStore>()((set) => ({
  suggestions: [],
  lastUpdated: null,
  isGenerating: false,

  setSuggestions: (suggestions) =>
    set({ suggestions, lastUpdated: Date.now() }),
  setIsGenerating: (isGenerating) => set({ isGenerating }),
  clearSuggestions: () =>
    set({ suggestions: [], lastUpdated: null }),
}));

// ── Summary Store ─────────────────────────────────────────────────────────────

interface SummaryStore {
  currentSummary: string | null;
  lastUpdated: number | null;
  isGenerating: boolean;

  setSummary: (summary: string) => void;
  setIsGenerating: (generating: boolean) => void;
  clearSummary: () => void;
}

export const useSummaryStore = create<SummaryStore>()((set) => ({
  currentSummary: null,
  lastUpdated: null,
  isGenerating: false,

  setSummary: (summary) =>
    set({ currentSummary: summary, lastUpdated: Date.now() }),
  setIsGenerating: (isGenerating) => set({ isGenerating }),
  clearSummary: () => set({ currentSummary: null, lastUpdated: null }),
}));

// ── Action Items Store ────────────────────────────────────────────────────────

interface ActionItemsStore {
  items: ActionItem[];
  lastUpdated: number | null;

  setItems: (items: ActionItem[]) => void;
  addItem: (item: ActionItem) => void;
  clearItems: () => void;
}

export const useActionItemsStore = create<ActionItemsStore>()((set) => ({
  items: [],
  lastUpdated: null,

  setItems: (items) => set({ items, lastUpdated: Date.now() }),
  addItem: (item) =>
    set((state) => ({
      items: [...state.items, item],
      lastUpdated: Date.now(),
    })),
  clearItems: () => set({ items: [], lastUpdated: null }),
}));

// ── Chat Store ────────────────────────────────────────────────────────────────

interface ChatStore {
  messages: ChatMessage[];
  isStreaming: boolean;
  streamingMessageId: string | null;

  addMessage: (message: ChatMessage) => void;
  appendStreamToken: (token: string) => void;
  finalizeStreamingMessage: (fullContent: string) => void;
  startStreaming: (messageId: string) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatStore>()(
  subscribeWithSelector((set) => ({
    messages: [],
    isStreaming: false,
    streamingMessageId: null,

    addMessage: (message) =>
      set((state) => ({ messages: [...state.messages, message] })),

    startStreaming: (messageId) =>
      set((state) => ({
        isStreaming: true,
        streamingMessageId: messageId,
        messages: [
          ...state.messages,
          {
            id: messageId,
            role: "assistant",
            content: "",
            timestamp: Date.now(),
            isStreaming: true,
          },
        ],
      })),

    appendStreamToken: (token) =>
      set((state) => ({
        messages: state.messages.map((m) =>
          m.id === state.streamingMessageId
            ? { ...m, content: m.content + token }
            : m
        ),
      })),

    finalizeStreamingMessage: (fullContent) =>
      set((state) => ({
        isStreaming: false,
        streamingMessageId: null,
        messages: state.messages.map((m) =>
          m.id === state.streamingMessageId
            ? { ...m, content: fullContent, isStreaming: false }
            : m
        ),
      })),

    clearMessages: () =>
      set({ messages: [], isStreaming: false, streamingMessageId: null }),
  }))
);

// ── UI Store ──────────────────────────────────────────────────────────────────

interface UIStore {
  activePanel: OverlayPanel;
  isExpanded: boolean;
  stealthMode: boolean;
  opacity: number;

  setActivePanel: (panel: OverlayPanel) => void;
  setExpanded: (expanded: boolean) => void;
  setStealthMode: (stealth: boolean) => void;
  setOpacity: (opacity: number) => void;
  toggleExpanded: () => void;
}

export const useUIStore = create<UIStore>()((set) => ({
  activePanel: "transcript",
  isExpanded: true,
  stealthMode: false,
  opacity: 0.95,

  setActivePanel: (activePanel) => set({ activePanel }),
  setExpanded: (isExpanded) => set({ isExpanded }),
  setStealthMode: (stealthMode) => set({ stealthMode }),
  setOpacity: (opacity) => set({ opacity }),
  toggleExpanded: () => set((state) => ({ isExpanded: !state.isExpanded })),
}));
