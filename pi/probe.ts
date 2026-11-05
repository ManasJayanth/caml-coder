import { createAgentSession, SettingsManager, SessionManager } from "@earendil-works/pi-coding-agent";

// Import-only probe. Never creates a personal session or loads ambient resources.
if (typeof createAgentSession !== "function" ||
    typeof SettingsManager.inMemory !== "function" ||
    typeof SessionManager.inMemory !== "function") {
  throw new Error("Pinned Pi SDK lacks required entry points");
}
process.stdout.write(JSON.stringify({sdk: "@earendil-works/pi-coding-agent", version: "1.2.0", status: "PASSED", scope: "imports-only"}) + "\n");
