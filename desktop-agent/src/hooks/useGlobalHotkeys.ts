/**
 * Garage Meeting Copilot — Global Hotkey Hook
 * Registers Tauri global shortcuts for overlay control.
 */
import { useEffect } from "react";
import { safeInvoke, isTauri } from "@/lib/tauri";
import { useUIStore } from "@/stores";

const HOTKEYS = {
  toggleOverlay: "CommandOrControl+Shift+G",
  toggleStealth: "CommandOrControl+Shift+S",
  focusChat: "CommandOrControl+Shift+C",
};

export function useGlobalHotkeys() {
  const toggleExpanded = useUIStore((s) => s.toggleExpanded);
  const setStealthMode = useUIStore((s) => s.setStealthMode);
  const stealthMode = useUIStore((s) => s.stealthMode);
  const setActivePanel = useUIStore((s) => s.setActivePanel);

  useEffect(() => {
    let registered = false;

    const setup = async () => {
      // Global shortcuts only work inside a real Tauri app
      if (!isTauri()) return;
      try {
        const { register } = await import("@tauri-apps/plugin-global-shortcut");

        // Toggle overlay visibility
        await register(HOTKEYS.toggleOverlay, async () => {
          await safeInvoke("toggle_overlay_visibility");
          toggleExpanded();
        });

        // Toggle stealth (click-through) mode
        await register(HOTKEYS.toggleStealth, async () => {
          const newStealth = !stealthMode;
          await safeInvoke("set_overlay_stealth_mode", { enabled: newStealth });
          setStealthMode(newStealth);
        });

        // Focus chat panel
        await register(HOTKEYS.focusChat, () => {
          setActivePanel("chat");
          safeInvoke("toggle_overlay_visibility");
        });

        registered = true;
      } catch (err) {
        // Global shortcuts may fail if already registered or permission denied
        console.debug("[Hotkeys] Could not register global shortcuts:", err);
      }
    };

    setup();

    return () => {
      if (registered) {
        import("@tauri-apps/plugin-global-shortcut").then(({ unregister }) => {
          Promise.all([
            unregister(HOTKEYS.toggleOverlay).catch(() => {}),
            unregister(HOTKEYS.toggleStealth).catch(() => {}),
            unregister(HOTKEYS.focusChat).catch(() => {}),
          ]);
        }).catch(() => {});
      }
    };
  }, [toggleExpanded, setStealthMode, stealthMode, setActivePanel]);
}
