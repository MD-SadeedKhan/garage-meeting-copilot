/**
 * Garage Meeting Copilot — Complete Overlay with Setup Flow
 * Routes between setup screen and live copilot view.
 */
import { AnimatePresence, motion } from "framer-motion";
import { Bot } from "lucide-react";
import { useGlobalHotkeys } from "@/hooks/useGlobalHotkeys";
import { useSessionStore, useUIStore } from "@/stores";
import { SessionSetupScreen } from "./SessionSetupScreen";

// Re-export the main overlay that wraps setup + live view
export { CopilotOverlay } from "./CopilotOverlay";
export { SessionSetupScreen } from "./SessionSetupScreen";
