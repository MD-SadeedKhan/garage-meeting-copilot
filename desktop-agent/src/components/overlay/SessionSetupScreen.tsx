/**
 * Garage Meeting Copilot — Session Setup Screen
 * Shown when no session is active. Allows the user to configure
 * and start audio capture for a meeting.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { safeInvoke } from "@/lib/tauri";
import { Mic, Monitor, Radio, Settings, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useSessionStore,
  useUIStore,
  type CopilotSession,
} from "@/stores";

interface AudioDevice {
  id: string;
  name: string;
  is_default: boolean;
  device_type: string;
}

export function SessionSetupScreen() {
  const garageToken = useSessionStore((s) => s.garageToken);
  const gatewayUrl = useSessionStore((s) => s.gatewayUrl);
  const setSession = useSessionStore((s) => s.setSession);
  const setGarageToken = useSessionStore((s) => s.setGarageToken);
  const setAudioCaptureActive = useSessionStore((s) => s.setAudioCaptureActive);
  const isMicEnabled = useSessionStore((s) => s.isMicEnabled);
  const isSystemAudioEnabled = useSessionStore((s) => s.isSystemAudioEnabled);
  const setMicEnabled = useSessionStore((s) => s.setMicEnabled);
  const setSystemAudioEnabled = useSessionStore((s) => s.setSystemAudioEnabled);

  const [meetingId, setMeetingId] = useState("");
  const [tokenInput, setTokenInput] = useState(garageToken ?? "");
  const [apiBaseUrl, setApiBaseUrl] = useState(
    import.meta.env.VITE_API_BASE_URL || "http://localhost:8080"
  );
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleStart = async () => {
    if (!meetingId.trim() || !tokenInput.trim()) {
      setError("Meeting ID and authentication token are required.");
      return;
    }

    setIsStarting(true);
    setError(null);

    try {
      // 1. Create copilot session via REST API
      const resp = await fetch(`${apiBaseUrl}/api/v1/copilot/sessions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${tokenInput}`,
        },
        body: JSON.stringify({ garage_meeting_id: meetingId }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || "Failed to create session");
      }

      const sessionData = await resp.json();
      const sessionId: string = sessionData.id;

      // 2. Store token and session in Zustand
      setGarageToken(tokenInput);
      setSession({
        sessionId,
        garrageMeetingId: meetingId,
        userId: sessionData.user_id || "unknown",
        organizationId: sessionData.organization_id || "unknown",
        status: "active",
        startedAt: Date.now(),
      });

      // 3. Start audio capture (Tauri invoke if available; desktop agent handles it natively)
      const audioResult = await safeInvoke<{ success: boolean; error?: string }>(
        "start_audio_capture",
        {
          gatewayUrl,
          sessionId,
          token: tokenInput,
          enableMic: isMicEnabled,
          enableSystemAudio: isSystemAudioEnabled,
          micDeviceId: null,
          systemDeviceId: null,
        },
        { success: true } // fallback when running in browser/PyQt6 — agent handles audio
      );

      if (audioResult && !audioResult.success) {
        throw new Error(audioResult.error || "Failed to start audio capture");
      }

      setAudioCaptureActive(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsStarting(false);
    }
  };

  return (
    <div className="flex flex-col h-full p-4 gap-4 overflow-y-auto"
      style={{ scrollbarWidth: "thin", scrollbarColor: "#3f3f46 transparent" }}>

      {/* Header */}
      <div className="flex flex-col gap-1">
        <h2 className="text-sm font-semibold text-zinc-100">Start Copilot</h2>
        <p className="text-[11px] text-zinc-500">
          Connect to a Garage meeting to enable AI assistance.
        </p>
      </div>

      {/* Meeting ID */}
      <div className="flex flex-col gap-1.5">
        <label className="text-[11px] font-medium text-zinc-400">
          Meeting ID
        </label>
        <input
          type="text"
          value={meetingId}
          onChange={(e) => setMeetingId(e.target.value)}
          placeholder="meeting_xxxxxxxx"
          className="w-full px-3 py-2 rounded-lg bg-white/6 border border-white/10 text-xs text-zinc-200 placeholder-zinc-600 outline-none focus:border-violet-500/50 transition-colors"
        />
      </div>

      {/* Token */}
      <div className="flex flex-col gap-1.5">
        <label className="text-[11px] font-medium text-zinc-400">
          Garage Auth Token
        </label>
        <input
          type="password"
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
          className="w-full px-3 py-2 rounded-lg bg-white/6 border border-white/10 text-xs text-zinc-200 placeholder-zinc-600 outline-none focus:border-violet-500/50 transition-colors font-mono"
        />
        <p className="text-[10px] text-zinc-600">
          Your Garage JWT token. Stored securely on device.
        </p>
      </div>

      {/* Audio options */}
      <div className="flex flex-col gap-2">
        <label className="text-[11px] font-medium text-zinc-400">
          Audio Sources
        </label>

        <button
          onClick={() => setMicEnabled(!isMicEnabled)}
          className={cn(
            "flex items-center gap-2.5 px-3 py-2 rounded-lg border text-xs transition-all",
            isMicEnabled
              ? "bg-violet-600/15 border-violet-500/30 text-violet-300"
              : "bg-white/4 border-white/8 text-zinc-400 hover:border-white/15"
          )}
        >
          <Mic className="w-3.5 h-3.5 shrink-0" />
          <span className="flex-1 text-left">Microphone</span>
          <span className={cn(
            "text-[10px] font-medium px-1.5 py-0.5 rounded",
            isMicEnabled ? "bg-violet-500/20 text-violet-400" : "bg-zinc-700/50 text-zinc-500"
          )}>
            {isMicEnabled ? "ON" : "OFF"}
          </span>
        </button>

        <button
          onClick={() => setSystemAudioEnabled(!isSystemAudioEnabled)}
          className={cn(
            "flex items-center gap-2.5 px-3 py-2 rounded-lg border text-xs transition-all",
            isSystemAudioEnabled
              ? "bg-sky-600/15 border-sky-500/30 text-sky-300"
              : "bg-white/4 border-white/8 text-zinc-400 hover:border-white/15"
          )}
        >
          <Monitor className="w-3.5 h-3.5 shrink-0" />
          <span className="flex-1 text-left">System Audio</span>
          <span className={cn(
            "text-[10px] font-medium px-1.5 py-0.5 rounded",
            isSystemAudioEnabled ? "bg-sky-500/20 text-sky-400" : "bg-zinc-700/50 text-zinc-500"
          )}>
            {isSystemAudioEnabled ? "ON" : "OFF"}
          </span>
        </button>
      </div>

      {/* Advanced settings */}
      <div className="flex flex-col gap-2">
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-400 transition-colors"
        >
          <Settings className="w-3 h-3" />
          {showAdvanced ? "Hide" : "Show"} advanced settings
        </button>

        {showAdvanced && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            className="flex flex-col gap-1.5"
          >
            <label className="text-[11px] font-medium text-zinc-400">API Base URL</label>
            <input
              type="text"
              value={apiBaseUrl}
              onChange={(e) => setApiBaseUrl(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-white/6 border border-white/10 text-xs text-zinc-200 outline-none focus:border-violet-500/50 font-mono"
            />
          </motion.div>
        )}
      </div>

      {/* Error */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-400"
        >
          {error}
        </motion.div>
      )}

      {/* Start button */}
      <button
        onClick={handleStart}
        disabled={isStarting || !meetingId.trim() || !tokenInput.trim()}
        className={cn(
          "flex items-center justify-center gap-2 w-full py-2.5 rounded-lg text-sm font-medium transition-all",
          isStarting || !meetingId.trim() || !tokenInput.trim()
            ? "bg-zinc-700/50 text-zinc-500 cursor-not-allowed"
            : "bg-violet-600 hover:bg-violet-500 text-white shadow-md shadow-violet-500/20 active:scale-[0.98]"
        )}
      >
        {isStarting ? (
          <>
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Starting...
          </>
        ) : (
          <>
            <Zap className="w-4 h-4" />
            Start AI Copilot
          </>
        )}
      </button>

      <p className="text-[10px] text-zinc-600 text-center">
        Ctrl+Shift+G to toggle overlay · Ctrl+Shift+S for stealth mode
      </p>
    </div>
  );
}
