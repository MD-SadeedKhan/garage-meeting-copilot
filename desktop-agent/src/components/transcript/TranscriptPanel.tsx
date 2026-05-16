/**
 * Garage Meeting Copilot — Transcript Panel
 * Realtime transcript rendering with speaker diarization.
 */
import { AnimatePresence, motion } from "framer-motion";
import { Mic, MicOff } from "lucide-react";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { useTranscriptStore } from "@/stores";
import type { TranscriptChunk } from "@/stores";

// Speaker color palette
const SPEAKER_COLORS: Record<string, string> = {
  "Speaker 1": "text-violet-400",
  "Speaker 2": "text-sky-400",
  "Speaker 3": "text-emerald-400",
  "Speaker 4": "text-amber-400",
  "Speaker 5": "text-rose-400",
};

function getSpeakerColor(speaker: string | null): string {
  if (!speaker) return "text-zinc-300";
  return SPEAKER_COLORS[speaker] ?? "text-zinc-300";
}

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ── Individual Chunk ──────────────────────────────────────────────────────────

interface ChunkItemProps {
  chunk: TranscriptChunk;
}

function ChunkItem({ chunk }: ChunkItemProps) {
  const speakerColor = getSpeakerColor(chunk.speakerLabel);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex flex-col gap-1.5 px-4 py-2.5 group hover:bg-white/6 rounded-lg transition-colors border border-white/0 group-hover:border-white/5"
    >
      <div className="flex items-center gap-2.5">
        <span className={cn("text-[10px] font-bold tracking-widest uppercase", speakerColor)}>
          {chunk.speakerLabel ?? "Speaker"}
        </span>
        <span className="text-[9px] text-zinc-600 font-mono tabular-nums">
          {formatTimestamp(chunk.startTime)}
        </span>
        {chunk.is_final && (
          <div className="ml-auto flex h-1.5 w-1.5 rounded-full bg-emerald-400/60" />
        )}
      </div>
      <p className="text-xs text-zinc-100 leading-relaxed font-medium tracking-tight">{chunk.text}</p>
    </motion.div>
  );
}

// ── Pending (interim) chunk ───────────────────────────────────────────────────

function PendingChunk({ chunk }: { chunk: TranscriptChunk }) {
  return (
    <div className="flex flex-col gap-1.5 px-4 py-2.5 opacity-70 border border-white/5 rounded-lg">
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            "text-[10px] font-bold tracking-widest uppercase",
            getSpeakerColor(chunk.speakerLabel)
          )}
        >
          {chunk.speakerLabel ?? "Speaker"}
        </span>
        <span className="flex gap-0.5 items-end">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="inline-block w-1 h-1 bg-violet-400 rounded-full animate-bounce"
              style={{ animationDelay: `${i * 0.1}s` }}
            />
          ))}
        </span>
      </div>
      <p className="text-xs text-zinc-400 italic leading-relaxed font-medium">
        {chunk.text}
      </p>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center">
      <div className="flex items-center justify-center w-12 h-12 rounded-full bg-gradient-to-br from-violet-500/20 to-indigo-600/20 border border-violet-400/30">
        <Mic className="w-6 h-6 text-violet-400/60" strokeWidth={1.5} />
      </div>
      <div>
        <p className="text-sm font-semibold text-zinc-300">
          Waiting for speech
        </p>
        <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
          Start speaking and the transcript will appear here in real-time.
        </p>
      </div>
    </div>
  );
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function TranscriptPanel() {
  const chunks = useTranscriptStore((s) => s.chunks);
  const pendingChunk = useTranscriptStore((s) => s.pendingChunk);
  const totalChunks = useTranscriptStore((s) => s.totalChunks);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new chunks
  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      const isNearBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      if (isNearBottom) {
        el.scrollTop = el.scrollHeight;
      }
    }
  }, [chunks, pendingChunk]);

  const hasContent = chunks.length > 0 || pendingChunk;

  return (
    <div className="flex flex-col h-full">
      {/* Stats bar */}
      {hasContent && (
        <div className="flex items-center gap-3 px-3 py-1 border-b border-white/5 bg-black/10">
          <span className="text-[10px] text-zinc-500">
            {totalChunks} segment{totalChunks !== 1 ? "s" : ""}
          </span>
          <span className="flex items-center gap-1 text-[10px] text-emerald-500">
            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
            Live
          </span>
        </div>
      )}

      {/* Scrollable transcript */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto overscroll-contain py-1 scroll-smooth"
        style={{ scrollbarWidth: "thin", scrollbarColor: "#3f3f46 transparent" }}
      >
        {!hasContent ? (
          <EmptyState />
        ) : (
          <div className="flex flex-col gap-0.5">
            <AnimatePresence initial={false}>
              {chunks.map((chunk) => (
                <ChunkItem key={chunk.chunkId} chunk={chunk} />
              ))}
            </AnimatePresence>

            {/* Pending interim chunk */}
            {pendingChunk && (
              <PendingChunk key="pending" chunk={pendingChunk} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
