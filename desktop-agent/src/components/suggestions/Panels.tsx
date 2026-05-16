/**
 * Garage Meeting Copilot — Suggestions Panel
 */
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  CheckCircle2,
  HelpCircle,
  Lightbulb,
  ListChecks,
  MessageCircle,
  RefreshCw,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSuggestionsStore, type Suggestion } from "@/stores";

const SUGGESTION_ICONS = {
  answer: <CheckCircle2 className="w-3 h-3" strokeWidth={2} />,
  talking_point: <Lightbulb className="w-3 h-3" strokeWidth={2} />,
  insight: <Zap className="w-3 h-3" strokeWidth={2} />,
  objection: <MessageCircle className="w-3 h-3" strokeWidth={2} />,
  followup: <ArrowRight className="w-3 h-3" strokeWidth={2} />,
  // legacy types
  question: <HelpCircle className="w-3 h-3" strokeWidth={2} />,
  clarification: <MessageCircle className="w-3 h-3" strokeWidth={2} />,
  fact: <Zap className="w-3 h-3" strokeWidth={2} />,
  action: <ListChecks className="w-3 h-3" strokeWidth={2} />,
};

const SUGGESTION_COLORS = {
  answer: "bg-emerald-500/20 text-emerald-200 border-emerald-400/30",
  talking_point: "bg-violet-500/20 text-violet-200 border-violet-400/30",
  insight: "bg-amber-500/20 text-amber-200 border-amber-400/30",
  objection: "bg-rose-500/20 text-rose-200 border-rose-400/30",
  followup: "bg-sky-500/20 text-sky-200 border-sky-400/30",
  // legacy types
  question: "bg-violet-500/20 text-violet-200 border-violet-400/30",
  clarification: "bg-sky-500/20 text-sky-200 border-sky-400/30",
  fact: "bg-amber-500/20 text-amber-200 border-amber-400/30",
  action: "bg-emerald-500/20 text-emerald-200 border-emerald-400/30",
};

function SuggestionCard({ suggestion, index }: { suggestion: Suggestion; index: number }) {
  const color = SUGGESTION_COLORS[suggestion.type];
  const icon = SUGGESTION_ICONS[suggestion.type];

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.2 }}
      className={cn(
        "flex flex-col gap-2 p-3 rounded-lg border",
        "bg-white/5 hover:bg-white/8 transition-colors cursor-default backdrop-blur-sm",
        "border-white/10"
      )}
    >
      <div className="flex items-center gap-2">
        <span className={cn("flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] font-bold border uppercase tracking-wide", color)}>
          {icon}
          {suggestion.type}
        </span>
        <span className="text-[10px] text-zinc-500 ml-auto font-semibold">
          {Math.round(suggestion.confidence * 100)}%
        </span>
      </div>
      <p className="text-xs text-zinc-100 leading-relaxed font-medium">{suggestion.content}</p>
      {suggestion.contextExcerpt && (
        <p className="text-[10px] text-zinc-400 italic border-l-2 border-violet-500/40 pl-2">
          "{suggestion.contextExcerpt}"
        </p>
      )}
    </motion.div>
  );
}

export function SuggestionsPanel() {
  const suggestions = useSuggestionsStore((s) => s.suggestions);
  const lastUpdated = useSuggestionsStore((s) => s.lastUpdated);

  const timeAgo = lastUpdated
    ? Math.round((Date.now() - lastUpdated) / 1000)
    : null;

  return (
    <div className="flex flex-col h-full">
      {suggestions.length > 0 && (
        <div className="flex items-center gap-2.5 px-4 py-2 border-b border-white/8 text-[10px] text-zinc-500 bg-white/3 backdrop-blur-sm">
          <RefreshCw className="w-3 h-3 animate-spin opacity-60" />
          <span className="font-medium">{timeAgo !== null ? `Updated ${timeAgo}s ago` : "Generating..."}</span>
        </div>
      )}
      <div
        className="flex-1 overflow-y-auto p-3 flex flex-col gap-2.5"
        style={{ scrollbarWidth: "thin", scrollbarColor: "#3f3f46 transparent" }}
      >
        {suggestions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-4">
            <Lightbulb className="w-8 h-8 text-violet-500/50" strokeWidth={1.5} />
            <div>
              <p className="text-sm font-semibold text-zinc-300">No suggestions yet</p>
              <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
                Smart suggestions will appear as the conversation develops.
              </p>
            </div>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {suggestions.map((s, i) => (
              <SuggestionCard key={`${s.type}-${i}`} suggestion={s} index={i} />
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

/**
 * Summary Panel
 */
import { FileText, Clock } from "lucide-react";
import { useSummaryStore } from "@/stores";

export function SummaryPanel() {
  const summary = useSummaryStore((s) => s.currentSummary);
  const lastUpdated = useSummaryStore((s) => s.lastUpdated);

  const timeAgo = lastUpdated
    ? Math.round((Date.now() - lastUpdated) / 1000)
    : null;

  return (
    <div className="flex flex-col h-full">
      {summary && (
        <div className="flex items-center gap-2.5 px-4 py-2 border-b border-white/8 text-[10px] text-zinc-500 bg-white/3 backdrop-blur-sm">
          <Clock className="w-3 h-3 animate-spin opacity-60" />
          <span className="font-medium">{timeAgo !== null ? `Updated ${timeAgo}s ago` : "Generating..."}</span>
        </div>
      )}
      <div
        className="flex-1 overflow-y-auto p-4"
        style={{ scrollbarWidth: "thin", scrollbarColor: "#3f3f46 transparent" }}
      >
        {!summary ? (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-4">
            <FileText className="w-8 h-8 text-violet-500/50" strokeWidth={1.5} />
            <div>
              <p className="text-sm font-semibold text-zinc-300">No summary yet</p>
              <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
                Rolling summary appears after a few minutes of discussion.
              </p>
            </div>
          </div>
        ) : (
          <motion.div
            key={lastUpdated}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="prose prose-invert prose-xs max-w-none"
          >
            <div className="text-xs text-zinc-100 leading-relaxed whitespace-pre-wrap font-medium">
              {summary}
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
}

/**
 * Action Items Panel
 */
import { CheckSquare, AlertTriangle, User, Calendar } from "lucide-react";
import { useActionItemsStore, type ActionItem } from "@/stores";

const PRIORITY_STYLES = {
  low: "text-zinc-400 bg-zinc-800/40 border-white/10",
  medium: "text-sky-300 bg-sky-500/15 border-sky-400/30",
  high: "text-amber-300 bg-amber-500/15 border-amber-400/30",
  critical: "text-red-300 bg-red-500/15 border-red-400/30",
};

function ActionItemCard({ item }: { item: ActionItem }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-2 p-3 rounded-lg border border-white/10 bg-white/5 hover:bg-white/8 transition-colors backdrop-blur-sm"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold text-zinc-100 leading-snug flex-1">
          {item.title}
        </p>
        <span
          className={cn(
            "shrink-0 text-[9px] font-bold uppercase px-2 py-0.5 rounded-md border",
            PRIORITY_STYLES[item.priority]
          )}
        >
          {item.priority}
        </span>
      </div>
      {item.description && (
        <p className="text-[10px] text-zinc-300 leading-snug">{item.description}</p>
      )}
      <div className="flex items-center gap-2.5 mt-1 flex-wrap">
        {item.assignee && (
          <span className="flex items-center gap-1.5 text-[10px] text-zinc-400">
            <User className="w-3 h-3 opacity-60" strokeWidth={2} />
            {item.assignee}
          </span>
        )}
        {item.dueDate && (
          <span className="flex items-center gap-1.5 text-[10px] text-zinc-400">
            <Calendar className="w-3 h-3 opacity-60" strokeWidth={2} />
            {item.dueDate}
          </span>
        )}
        <span className="text-[9px] text-zinc-500 ml-auto font-semibold">
          {Math.round(item.confidenceScore * 100)}%
        </span>
      </div>
    </motion.div>
  );
}

export function ActionItemsPanel() {
  const items = useActionItemsStore((s) => s.items);

  return (
    <div className="flex flex-col h-full">
      {items.length > 0 && (
        <div className="flex items-center gap-2.5 px-4 py-2 border-b border-white/8 text-[10px] text-zinc-500 bg-white/3 backdrop-blur-sm">
          <CheckSquare className="w-3 h-3 text-emerald-400" strokeWidth={2} />
          <span className="font-medium">{items.length} action item{items.length !== 1 ? "s" : ""}</span>
        </div>
      )}
      <div
        className="flex-1 overflow-y-auto p-3 flex flex-col gap-2.5"
        style={{ scrollbarWidth: "thin", scrollbarColor: "#3f3f46 transparent" }}
      >
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-4">
            <CheckSquare className="w-8 h-8 text-emerald-500/50" strokeWidth={1.5} />
            <div>
              <p className="text-sm font-semibold text-zinc-300">No action items yet</p>
              <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
                Items will be extracted from the conversation automatically.
              </p>
            </div>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {items.map((item, i) => (
              <ActionItemCard key={item.title + i} item={item} />
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

/**
 * Chat Panel — AI contextual chat
 */
import { Send, Bot } from "lucide-react";
import { useRef, useState, KeyboardEvent } from "react";
import { useChatStore, type ChatMessage } from "@/stores";

function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("flex gap-2.5", isUser ? "flex-row-reverse" : "flex-row")}
    >
      {!isUser && (
        <div className="shrink-0 flex items-center justify-center w-6 h-6 rounded-full bg-gradient-to-br from-violet-500/60 to-indigo-600/60 mt-0.5 border border-white/10">
          <Bot className="w-3.5 h-3.5 text-white" strokeWidth={2} />
        </div>
      )}
      <div
        className={cn(
          "max-w-[85%] px-3 py-2 rounded-xl text-xs leading-relaxed font-medium",
          isUser
            ? "bg-gradient-to-br from-violet-600/60 to-violet-700/40 text-white rounded-tr-sm border border-violet-400/20"
            : "bg-white/8 text-zinc-100 rounded-tl-sm border border-white/10 backdrop-blur-sm"
        )}
      >
        {message.content}
        {message.isStreaming && (
          <span className="inline-block w-1.5 h-3 bg-violet-400 rounded-sm ml-1 animate-pulse" />
        )}
      </div>
    </motion.div>
  );
}

interface ChatPanelProps {
  onSendMessage: (message: string) => void;
}

export function ChatPanel({ onSendMessage }: ChatPanelProps) {
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const addMessage = useChatStore((s) => s.addMessage);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const { v4: uuidv4 } = { v4: () => Math.random().toString(36).slice(2) };

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    // Add user message to store
    addMessage({
      id: Math.random().toString(36).slice(2),
      role: "user",
      content: trimmed,
      timestamp: Date.now(),
    });

    onSendMessage(trimmed);
    setInput("");

    // Scroll to bottom
    setTimeout(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    }, 50);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 flex flex-col gap-3"
        style={{ scrollbarWidth: "thin", scrollbarColor: "#3f3f46 transparent" }}
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-4">
            <Bot className="w-8 h-8 text-violet-500/50" strokeWidth={1.5} />
            <div>
              <p className="text-sm font-semibold text-zinc-300">Chat with the AI</p>
              <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
                Ask questions about the meeting using context from transcripts.
              </p>
            </div>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <ChatBubble key={m.id} message={m} />
            ))}
          </AnimatePresence>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-white/8 bg-white/3 backdrop-blur-sm p-3">
        <div className="flex items-end gap-2 bg-white/6 rounded-lg px-3 py-2 border border-white/10 focus-within:border-violet-400/50 transition-colors hover:border-white/20">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about the meeting..."
            disabled={isStreaming}
            rows={1}
            className={cn(
              "flex-1 bg-transparent text-xs text-zinc-100 placeholder-zinc-500 font-medium",
              "outline-none resize-none max-h-20 leading-relaxed py-0.5",
              isStreaming && "opacity-60 cursor-not-allowed"
            )}
            style={{ scrollbarWidth: "none" }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            className={cn(
              "flex items-center justify-center w-7 h-7 rounded-lg transition-all border",
              input.trim() && !isStreaming
                ? "bg-gradient-to-br from-violet-500/60 to-violet-600/40 hover:from-violet-500/80 hover:to-violet-600/60 text-white border-violet-400/30 shadow-lg shadow-violet-500/20"
                : "bg-zinc-700/30 text-zinc-500 cursor-not-allowed border-white/5"
            )}
          >
            <Send className="w-3.5 h-3.5" strokeWidth={2.5} />
          </button>
        </div>
        <p className="text-[9px] text-zinc-600 mt-1 px-1 font-medium">
          Shift+Enter for newline
        </p>
      </div>
    </div>
  );
}
