/**
 * Garage Meeting Copilot — Screen Capture Hook
 * Periodically captures the screen via Tauri and sends OCR context
 * to the gateway WebSocket for AI enrichment.
 */
import { useEffect, useRef } from "react";
import { safeInvoke } from "@/lib/tauri";

const CAPTURE_INTERVAL_MS = 10_000; // Every 10 seconds

interface ScreenCaptureResult {
  image_data: string;
  width: number;
  height: number;
}

interface UseScreenCaptureOptions {
  enabled: boolean;
  sessionId: string;
  onCapture: (
    extractedText: string,
    applicationName?: string,
    windowTitle?: string
  ) => void;
}

export function useScreenCapture({
  enabled,
  sessionId,
  onCapture,
}: UseScreenCaptureOptions) {
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isCapturing = useRef(false);

  const captureAndProcess = async () => {
    if (isCapturing.current || !enabled || !sessionId) return;
    isCapturing.current = true;

    try {
      // Capture screen via Tauri command (no-op in browser/PyQt6 mode)
      const result = await safeInvoke<{ success: boolean; data?: ScreenCaptureResult }>(
        "capture_screen",
        undefined,
        { success: false }
      );

      if (!result.success || !result.data) {
        return;
      }

      // Send screenshot to AI service OCR endpoint
      const response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"}/api/v1/copilot/ocr`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            image_data: result.data.image_data,
          }),
        }
      );

      if (response.ok) {
        const ocr = await response.json();
        if (ocr.cleaned_text && ocr.word_count > 5) {
          onCapture(
            ocr.cleaned_text,
            ocr.application_hint,
            undefined
          );
        }
      }
    } catch (error) {
      // Screen capture failures are non-fatal
      console.debug("[ScreenCapture] Capture failed (non-fatal):", error);
    } finally {
      isCapturing.current = false;
    }
  };

  useEffect(() => {
    if (!enabled) {
      if (timerRef.current) clearInterval(timerRef.current);
      return;
    }

    timerRef.current = setInterval(captureAndProcess, CAPTURE_INTERVAL_MS);

    // Capture immediately on enable
    captureAndProcess();

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, sessionId]);
}
