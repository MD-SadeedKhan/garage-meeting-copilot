/**
 * Garage Meeting Copilot — App Root
 * Handles Garage token injection and session bootstrap,
 * then renders the overlay assistant.
 */
import { useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import { safeListen } from "@/lib/tauri";
import { CopilotOverlay } from "@/components/overlay/CopilotOverlay";
import { useSessionStore, useUIStore } from "@/stores";

export default function App() {
  const setGarageToken = useSessionStore((s) => s.setGarageToken);
  const setSession = useSessionStore((s) => s.setSession);
  const setGatewayUrl = useSessionStore((s) => s.setGatewayUrl);
  const setAudioCaptureActive = useSessionStore((s) => s.setAudioCaptureActive);
  const setConnectionStatus = useSessionStore((s) => s.setConnectionStatus);

  useEffect(() => {
    // Tauri event listeners — only wire up when running inside a real Tauri app.
    // safeListen returns a no-op when Tauri is unavailable (browser / PyQt6).
    let unlistenAll: Promise<Array<() => void>> | null = null;
    unlistenAll = Promise.all([
      safeListen("copilot:audio-started", () => setAudioCaptureActive(true)),
      safeListen("copilot:audio-stopped", () => setAudioCaptureActive(false)),
      safeListen("copilot:ws-connected",  () => setConnectionStatus("connected")),
      safeListen("copilot:stream-error",  (event) => {
        console.error("[Copilot] Stream error:", event.payload);
        setConnectionStatus("error");
        setAudioCaptureActive(false);
      }),
      safeListen("copilot:init-session", (event) => {
        const p = event.payload as {
          token: string; sessionId: string; garrageMeetingId: string;
          userId: string; organizationId: string; gatewayUrl?: string;
        };
        setGarageToken(p.token);
        setSession({
          sessionId: p.sessionId,
          garrageMeetingId: p.garrageMeetingId,
          userId: p.userId,
          organizationId: p.organizationId,
          status: "active",
          startedAt: Date.now(),
        });
        if (p.gatewayUrl) setGatewayUrl(p.gatewayUrl);
      }),
    ]);

    // Read initial config from URL hash.
    // Supports both full Garage params and minimal dev/desktop-agent params.
    const hash = window.location.hash.slice(1);
    if (hash) {
      try {
        const params = new URLSearchParams(hash);
        const token      = params.get("token");
        const sessionId  = params.get("session_id");
        const gatewayUrl = params.get("gateway_url");
        // Optional Garage-specific params — fall back to sensible defaults
        const meetingId  = params.get("meeting_id") ?? sessionId ?? "meeting_unknown";
        const userId     = params.get("user_id")    ?? "user_local";
        const orgId      = params.get("org_id")     ?? "org_local";

        if (token && sessionId) {
          setGarageToken(token);
          setSession({
            sessionId,
            garrageMeetingId: meetingId,
            userId,
            organizationId: orgId,
            status: "active",
            startedAt: Date.now(),
          });
          if (gatewayUrl) setGatewayUrl(decodeURIComponent(gatewayUrl));
        }
      } catch {
        // Non-fatal — overlay still renders
      }
    }

    return () => {
      unlistenAll?.then((fns) => fns.forEach((fn) => fn()));
    };
  }, []);

  return (
    <div className="w-screen h-screen overflow-hidden bg-transparent">
      <AnimatePresence>
        <CopilotOverlay />
      </AnimatePresence>
    </div>
  );
}
