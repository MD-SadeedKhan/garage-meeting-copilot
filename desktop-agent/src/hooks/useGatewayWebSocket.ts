/**
 * Garage Meeting Copilot — WebSocket Gateway Hook
 * Manages the WebSocket connection to the realtime gateway.
 * Dispatches all incoming events to the appropriate Zustand stores.
 */
import { useCallback, useEffect, useRef } from "react";
import { v4 as uuidv4 } from "uuid";
import {
  useActionItemsStore,
  useChatStore,
  useSessionStore,
  useSuggestionsStore,
  useSummaryStore,
  useTranscriptStore,
} from "@/stores";

const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 5;
const PING_INTERVAL_MS = 25000;

interface UseGatewayWebSocketOptions {
  sessionId: string;
  token: string;
  gatewayUrl: string;
  enabled: boolean;
}

export function useGatewayWebSocket({
  sessionId,
  token,
  gatewayUrl,
  enabled,
}: UseGatewayWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const isMounted = useRef(true);

  const setConnectionStatus = useSessionStore((s) => s.setConnectionStatus);
  const addChunk = useTranscriptStore((s) => s.addChunk);
  const setPendingChunk = useTranscriptStore((s) => s.setPendingChunk);
  const setSuggestions = useSuggestionsStore((s) => s.setSuggestions);
  const setSummary = useSummaryStore((s) => s.setSummary);
  const setActionItems = useActionItemsStore((s) => s.setItems);
  const appendStreamToken = useChatStore((s) => s.appendStreamToken);
  const finalizeStreamingMessage = useChatStore(
    (s) => s.finalizeStreamingMessage
  );
  const startStreaming = useChatStore((s) => s.startStreaming);

  const clearTimers = useCallback(() => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    if (pingTimer.current) clearInterval(pingTimer.current);
    reconnectTimer.current = null;
    pingTimer.current = null;
  }, []);

  const startPingLoop = useCallback((ws: WebSocket) => {
    pingTimer.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, PING_INTERVAL_MS);
  }, []);

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(event.data as string);
      } catch {
        console.warn("[Copilot WS] Invalid JSON received");
        return;
      }

      const eventType = data.event as string;

      switch (eventType) {
        case "connected":
          setConnectionStatus("connected");
          reconnectAttempts.current = 0;
          break;

        case "transcript": {
          const chunk = {
            chunkId: data.chunk_id as string,
            sessionId: data.session_id as string,
            text: data.text as string,
            speakerLabel: (data.speaker_label as string | null) ?? null,
            startTime: (data.start_time as number) ?? 0,
            endTime: (data.end_time as number) ?? 0,
            isFinal: (data.is_final as boolean) ?? false,
            sequenceNumber: (data.sequence_number as number) ?? 0,
          };
          if (chunk.isFinal) {
            addChunk(chunk);
          } else {
            setPendingChunk(chunk);
          }
          break;
        }

        case "suggestions": {
          const suggestions = data.suggestions as Array<{
            type: string;
            content: string;
            confidence: number;
            context_excerpt?: string;
          }>;
          setSuggestions(
            suggestions.map((s) => ({
              type: s.type as any,
              content: s.content,
              confidence: s.confidence,
              contextExcerpt: s.context_excerpt,
            }))
          );
          break;
        }

        case "summary":
          setSummary(data.content as string);
          break;

        case "action_items":
          setActionItems(
            (data.items as any[]).map((item) => ({
              title: item.title,
              description: item.description,
              assignee: item.assignee,
              dueDate: item.due_date,
              priority: item.priority ?? "medium",
              status: item.status ?? "open",
              confidenceScore: item.confidence_score ?? 0.9,
            }))
          );
          break;

        case "chat_token":
          appendStreamToken(data.token as string);
          break;

        case "chat_complete":
          finalizeStreamingMessage(data.full_response as string);
          break;

        case "pong":
          // Keepalive acknowledged
          break;

        case "error":
          console.error(
            `[Copilot WS] Server error: ${data.code} — ${data.message}`
          );
          break;

        default:
          break;
      }
    },
    [
      setConnectionStatus,
      addChunk,
      setPendingChunk,
      setSuggestions,
      setSummary,
      setActionItems,
      appendStreamToken,
      finalizeStreamingMessage,
    ]
  );

  const connect = useCallback(() => {
    if (!isMounted.current || !enabled) return;

    clearTimers();
    setConnectionStatus("connecting");

    const url = `${gatewayUrl}?token=${encodeURIComponent(token)}&session_id=${encodeURIComponent(sessionId)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!isMounted.current) {
        ws.close();
        return;
      }
      startPingLoop(ws);
      reconnectAttempts.current = 0;
    };

    ws.onmessage = handleMessage;

    ws.onclose = (event) => {
      clearTimers();

      if (!isMounted.current) return;

      if (event.code === 4001) {
        setConnectionStatus("error");
        console.error("[Copilot WS] Auth failed — check Garage JWT token");
        return;
      }

      if (event.code === 4004) {
        setConnectionStatus("error");
        console.error("[Copilot WS] Session not found");
        return;
      }

      if (
        reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS &&
        event.code !== 1000
      ) {
        reconnectAttempts.current += 1;
        setConnectionStatus("reconnecting");
        const delay =
          RECONNECT_DELAY_MS * Math.pow(1.5, reconnectAttempts.current - 1);
        reconnectTimer.current = setTimeout(connect, delay);
      } else {
        setConnectionStatus("disconnected");
      }
    };

    ws.onerror = () => {
      setConnectionStatus("error");
    };
  }, [
    enabled,
    gatewayUrl,
    token,
    sessionId,
    handleMessage,
    setConnectionStatus,
    clearTimers,
    startPingLoop,
  ]);

  const disconnect = useCallback(() => {
    clearTimers();
    if (wsRef.current) {
      wsRef.current.close(1000, "Client disconnected");
      wsRef.current = null;
    }
    setConnectionStatus("disconnected");
  }, [clearTimers, setConnectionStatus]);

  const sendAudioChunk = useCallback(
    (audioData: string, sequence: number, source: "microphone" | "system" | "mixed") => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: "audio",
            session_id: sessionId,
            data: audioData,
            sequence,
            source,
          })
        );
      }
    },
    [sessionId]
  );

  const sendChatMessage = useCallback(
    (message: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        const msgId = uuidv4();
        startStreaming(msgId);
        wsRef.current.send(
          JSON.stringify({
            type: "chat",
            session_id: sessionId,
            message,
          })
        );
      }
    },
    [sessionId, startStreaming]
  );

  const sendScreenContext = useCallback(
    (extractedText: string, applicationName?: string, windowTitle?: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: "screen_context",
            session_id: sessionId,
            extracted_text: extractedText,
            application_name: applicationName,
            window_title: windowTitle,
          })
        );
      }
    },
    [sessionId]
  );

  useEffect(() => {
    isMounted.current = true;
    if (enabled && sessionId && token) {
      connect();
    }
    return () => {
      isMounted.current = false;
      disconnect();
    };
  }, [enabled, sessionId, token, connect, disconnect]);

  return {
    sendAudioChunk,
    sendChatMessage,
    sendScreenContext,
    disconnect,
    reconnect: connect,
  };
}
