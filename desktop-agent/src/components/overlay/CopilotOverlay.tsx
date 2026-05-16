/**
 * Garage Meeting Copilot — Main Overlay Component
 * The primary floating AI assistant UI.
 */
import { AnimatePresence, motion } from "framer-motion";
import {
  AlignLeft,
  Bot,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  FileText,
  Lightbulb,
  Mic,
  MicOff,
  Monitor,
  Wifi,
  WifiOff,
  X,
  Zap,
} from "lucide-react";
import React, { useCallback, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import {
  useActionItemsStore,
  useChatStore,
  useSessionStore,
  useSuggestionsStore,
  useSummaryStore,
  useTranscriptStore,
  useUIStore,
  type OverlayPanel,
} from "@/stores";
import { TranscriptPanel } from "../transcript/TranscriptPanel";
import { SuggestionsPanel, SummaryPanel, ChatPanel, ActionItemsPanel } from "../suggestions/Panels";
import { useGatewayWebSocket } from "@/hooks/useGatewayWebSocket";
import { useScreenCapture } from "@/hooks/useScreenCapture";

// ── Connection Status Indicator ───────────────────────────────────────────────

function ConnectionIndicator() {
  const status = useSessionStore((s) => s.connectionStatus);

  const map = {
    connected: { color: "bg-emerald-400", label: "Live", pulse: true },
    connecting: { color: "bg-amber-400", label: "Connecting", pulse: true },
    reconnecting: { color: "bg-amber-400", label: "Reconnecting", pulse: true },
    disconnected: { color: "bg-zinc-500", label: "Offline", pulse: false },
    error: { color: "bg-red-500", label: "Error", pulse: false },
  };

  const { color, label, pulse } = map[status];

  return (
    <div className="flex items-center gap-1.5">
      <span className="relative flex h-2 w-2">
        <span
          className={cn(
            "absolute inline-flex h-full w-full rounded-full opacity-75",
            color,
            pulse && "animate-ping"
          )}
        />
        <span
          className={cn("relative inline-flex h-2 w-2 rounded-full", color)}
        />
      </span>
      <span className="text-xs text-zinc-400 font-medium">{label}</span>
    </div>
  );
}

// ── Panel Tab Button ──────────────────────────────────────────────────────────

interface TabButtonProps {
  panel: OverlayPanel;
  icon: React.ReactNode;
  label: string;
  badge?: number;
}

function TabButton({ panel, icon, label, badge }: TabButtonProps) {
  const activePanel = useUIStore((s) => s.activePanel);
  const setActivePanel = useUIStore((s) => s.setActivePanel);
  const isActive = activePanel === panel;

  return (
    <button
      onClick={() => setActivePanel(panel)}
      className={cn(
        "relative flex flex-col items-center gap-0.5 px-3 py-2 rounded-lg transition-all duration-200",
        "text-xs font-semibold select-none border",
        isActive
          ? "bg-gradient-to-b from-violet-500/40 to-violet-600/20 text-violet-200 border-violet-400/40 shadow-lg shadow-violet-500/10 backdrop-blur-sm"
          : "text-zinc-400 hover:text-zinc-200 hover:bg-white/8 border-white/0 hover:border-white/10"
      )}
      title={label}
    >
      {icon}
      <span className="hidden sm:block text-[10px] leading-none tracking-tight">{label}</span>
      {badge !== undefined && badge > 0 && (
        <span className="absolute -top-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-violet-500 text-[9px] font-bold text-white">
          {badge > 9 ? "9+" : badge}
        </span>
      )}
    </button>
  );
}

// ── Header ────────────────────────────────────────────────────────────────────

function OverlayHeader() {
  const toggleExpanded = useUIStore((s) => s.toggleExpanded);
  const isExpanded = useUIStore((s) => s.isExpanded);
  const isAudioActive = useSessionStore((s) => s.isAudioCaptureActive);
  const isMicEnabled = useSessionStore((s) => s.isMicEnabled);

  return (
    <div
      className="flex items-center justify-between px-4 py-3 border-b border-white/8 bg-gradient-to-r from-white/5 via-white/[0.02] to-transparent cursor-move"
      data-tauri-drag-region
    >
      {/* Logo & Identity */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500/80 via-violet-600 to-indigo-600 shadow-lg shadow-violet-500/20">
          <Bot className="w-4 h-4 text-white" strokeWidth={2.5} />
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-bold text-white leading-tight tracking-tight">
            Copilot
          </span>
          <span className="text-[10px] text-zinc-500 leading-tight font-medium">
            Live Meeting AI
          </span>
        </div>
      </div>

      {/* Status row */}
      <div className="flex items-center gap-2.5">
        <ConnectionIndicator />

        {/* Mic indicator */}
        <div
          className={cn(
            "flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[10px] font-semibold transition-all backdrop-blur-sm border",
            isAudioActive && isMicEnabled
              ? "bg-emerald-500/20 text-emerald-300 border-emerald-400/30"
              : "bg-zinc-800/40 text-zinc-400 border-white/10"
          )}
        >
          {isMicEnabled ? (
            <Mic className="w-3 h-3" strokeWidth={2.5} />
          ) : (
            <MicOff className="w-3 h-3" strokeWidth={2.5} />
          )}
        </div>

        {/* Collapse / expand */}
        <button
          onClick={toggleExpanded}
          className="flex items-center justify-center w-6 h-6 rounded-lg text-zinc-400 hover:text-violet-400 hover:bg-white/8 transition-all duration-200 border border-white/0 hover:border-white/10"
        >
          {isExpanded ? (
            <ChevronRight className="w-3.5 h-3.5" strokeWidth={2.5} />
          ) : (
            <ChevronLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
          )}
        </button>
      </div>
    </div>
  );
}

// ── Tab Bar ───────────────────────────────────────────────────────────────────

function TabBar() {
  const suggestions = useSuggestionsStore((s) => s.suggestions);
  const actionItems = useActionItemsStore((s) => s.items);

  return (
    <div className="flex items-center gap-1 px-3 py-2 border-b border-white/8 bg-gradient-to-r from-white/3 via-white/[0.01] to-transparent backdrop-blur-sm">
      <TabButton
        panel="transcript"
        icon={<AlignLeft className="w-4 h-4" strokeWidth={2} />}
        label="Live"
      />
      <TabButton
        panel="suggestions"
        icon={<Lightbulb className="w-4 h-4" strokeWidth={2} />}
        label="Suggest"
        badge={suggestions.length}
      />
      <TabButton
        panel="summary"
        icon={<FileText className="w-4 h-4" strokeWidth={2} />}
        label="Summary"
      />
      <TabButton
        panel="chat"
        icon={<Bot className="w-4 h-4" strokeWidth={2} />}
        label="Chat"
      />
      <TabButton
        panel="actions"
        icon={<CheckSquare className="w-4 h-4" strokeWidth={2} />}
        label="Actions"
        badge={actionItems.length}
      />
    </div>
  );
}

// ── Main Overlay ──────────────────────────────────────────────────────────────

export function CopilotOverlay() {
  const session = useSessionStore((s) => s.session);
  const garageToken = useSessionStore((s) => s.garageToken);
  const gatewayUrl = useSessionStore((s) => s.gatewayUrl);
  const isExpanded = useUIStore((s) => s.isExpanded);
  const opacity = useUIStore((s) => s.opacity);
  const activePanel = useUIStore((s) => s.activePanel);

  const enabled = !!session && !!garageToken;

  const { sendChatMessage, sendScreenContext } = useGatewayWebSocket({
    sessionId: session?.sessionId ?? "",
    token: garageToken ?? "",
    gatewayUrl,
    enabled,
  });

  useScreenCapture({
    enabled,
    sessionId: session?.sessionId ?? "",
    onCapture: sendScreenContext,
  });

  const panelComponents: Record<OverlayPanel, React.ReactNode> = {
    transcript: <TranscriptPanel />,
    suggestions: <SuggestionsPanel />,
    summary: <SummaryPanel />,
    chat: <ChatPanel onSendMessage={sendChatMessage} />,
    actions: <ActionItemsPanel />,
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, x: 20 }}
      animate={{ opacity, scale: 1, x: 0 }}
      exit={{ opacity: 0, scale: 0.95, x: 20 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className={cn(
        "flex flex-col w-full h-full overflow-hidden",
        "rounded-2xl border border-white/10",
        "glass-morphism-lg",
        "text-white select-none"
      )}
      style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
    >
      <OverlayHeader />

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            key="expanded-content"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="flex flex-col flex-1 min-h-0"
          >
            <TabBar />

            {/* Panel content */}
            <div className="flex-1 min-h-0 overflow-hidden">
              <AnimatePresence mode="wait">
                <motion.div
                  key={activePanel}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  transition={{ duration: 0.15 }}
                  className="h-full"
                >
                  {panelComponents[activePanel]}
                </motion.div>
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Collapsed mini-bar */}
      <AnimatePresence>
        {!isExpanded && (
          <motion.div
            key="collapsed"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex items-center gap-2 px-3 py-2 text-xs text-zinc-400"
          >
            <Zap className="w-3 h-3 text-violet-400" />
            <span>Copilot running in background</span>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
