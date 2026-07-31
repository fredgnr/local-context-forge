import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CompanionBridgeClient,
  CompanionBridgeError,
  configuredMcpBridgeEndpoint
} from "./bridgeClient";
import { createCompanionServer } from "./server";

function diagnosticCode(error: unknown): string {
  if (error instanceof CompanionBridgeError) {
    return error.code;
  }
  return "startup-failed";
}

async function main(): Promise<void> {
  const bridge = new CompanionBridgeClient(
    await configuredMcpBridgeEndpoint()
  );
  const server = createCompanionServer(bridge);
  const transport = new StdioServerTransport();
  let closing = false;
  const close = async () => {
    if (closing) {
      return;
    }
    closing = true;
    bridge.close();
    await server.close().catch(() => undefined);
  };
  process.once("SIGINT", () => void close());
  process.once("SIGTERM", () => void close());
  try {
    await server.connect(transport);
  } catch (error) {
    bridge.close();
    process.stderr.write(`[lcf-mcp] ${diagnosticCode(error)}\n`);
    process.exitCode = 1;
  }
}

void main();
