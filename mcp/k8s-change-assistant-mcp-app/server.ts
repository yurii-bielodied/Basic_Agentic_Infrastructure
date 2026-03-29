import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import fs from "node:fs/promises";
import path from "node:path";

type ChangeRequest = {
  cluster: string;
  namespace: string;
  deployment: string;
  currentImage: string;
  targetImage: string;
  currentReplicas: number;
  desiredReplicas: number;
};

type PodInfo = {
  name: string;
  ready: string;
  status: string;
  restarts: number;
  age: string;
  node: string;
};

type EventInfo = {
  type: "Normal" | "Warning";
  reason: string;
  object: string;
  age: string;
  message: string;
};

const DIST_DIR = path.join(import.meta.dirname, "dist");
const resourceUri = "ui://k8s-change-assistant/mcp-app.html";

const DEFAULT_REQUEST: ChangeRequest = {
  cluster: "dev-cluster",
  namespace: "prod",
  deployment: "payments-api",
  currentImage: "ghcr.io/example/payments-api:1.9.3",
  targetImage: "ghcr.io/example/payments-api:1.9.4",
  currentReplicas: 3,
  desiredReplicas: 3,
};

function normalizeRequest(args: Record<string, unknown> | undefined): ChangeRequest {
  return {
    cluster: toStringOrDefault(args?.cluster, DEFAULT_REQUEST.cluster),
    namespace: toStringOrDefault(args?.namespace, DEFAULT_REQUEST.namespace),
    deployment: toStringOrDefault(args?.deployment, DEFAULT_REQUEST.deployment),
    currentImage: toStringOrDefault(args?.currentImage, DEFAULT_REQUEST.currentImage),
    targetImage: toStringOrDefault(args?.targetImage, DEFAULT_REQUEST.targetImage),
    currentReplicas: toNumberOrDefault(args?.currentReplicas, DEFAULT_REQUEST.currentReplicas),
    desiredReplicas: toNumberOrDefault(args?.desiredReplicas, DEFAULT_REQUEST.desiredReplicas),
  };
}

function toStringOrDefault(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : fallback;
}

function toNumberOrDefault(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }

  return fallback;
}

function buildPods(request: ChangeRequest): PodInfo[] {
  const baseName = request.deployment;
  const desired = Math.max(1, request.desiredReplicas);

  return Array.from({ length: desired }, (_, index) => ({
    name: `${baseName}-7df9f7c4b${index}-x${index + 1}k9`,
    ready: "1/1",
    status: index === 0 ? "Running" : "Running",
    restarts: 0,
    age: `${18 + index}m`,
    node: `worker-${(index % 2) + 1}`,
  }));
}

function buildEvents(request: ChangeRequest): EventInfo[] {
  return [
    {
      type: "Normal",
      reason: "ScalingReplicaSet",
      object: `deployment/${request.deployment}`,
      age: "14m",
      message: `Scaled up replica set ${request.deployment}-7df9f7c4b to ${request.currentReplicas}`,
    },
    {
      type: "Normal",
      reason: "Pulled",
      object: `pod/${request.deployment}-7df9f7c4b0-x1k9`,
      age: "13m",
      message: `Container image \"${request.currentImage}\" already present on machine`,
    },
    {
      type: "Normal",
      reason: "Started",
      object: `pod/${request.deployment}-7df9f7c4b0-x1k9`,
      age: "13m",
      message: "Started container app",
    },
  ];
}

function buildDeploymentStatus(request: ChangeRequest) {
  const imageWillChange = request.currentImage !== request.targetImage;
  const replicasWillChange = request.currentReplicas !== request.desiredReplicas;

  return {
    cluster: request.cluster,
    namespace: request.namespace,
    deployment: request.deployment,
    currentImage: request.currentImage,
    targetImage: request.targetImage,
    currentReplicas: request.currentReplicas,
    desiredReplicas: request.desiredReplicas,
    availableReplicas: request.currentReplicas,
    readyReplicas: request.currentReplicas,
    observedGeneration: 12,
    conditions: [
      { type: "Available", status: "True", reason: "MinimumReplicasAvailable" },
      { type: "Progressing", status: "True", reason: "NewReplicaSetAvailable" },
    ],
    changesDetected: {
      imageWillChange,
      replicasWillChange,
    },
    generatedAt: new Date().toISOString(),
  };
}

function buildSummary(request: ChangeRequest) {
  const risks: string[] = [];
  const actions: string[] = [];

  if (request.currentImage !== request.targetImage) {
    risks.push("Image tag changes may introduce application regressions.");
    actions.push("Verify readiness probes and 5xx error rate after rollout.");
  }

  if (request.currentReplicas !== request.desiredReplicas) {
    risks.push("Replica count change may alter capacity and scheduling pressure.");
    actions.push("Check CPU, memory, and pending pods after scaling.");
  }

  if (risks.length === 0) {
    risks.push("No risky configuration drift detected in this dry run.");
    actions.push("Still verify deployment health after the change window opens.");
  }

  return {
    title: "Dry-run change summary",
    summary:
      `Planned change for ${request.deployment} in ${request.namespace}: ` +
      `${request.currentImage} → ${request.targetImage}; ` +
      `${request.currentReplicas} replicas → ${request.desiredReplicas} replicas.`,
    risks,
    recommendedChecks: actions,
    approvalSuggestion: request.currentImage !== request.targetImage ? "manual-review" : "standard-change",
    generatedAt: new Date().toISOString(),
  };
}

function buildDryRun(request: ChangeRequest) {
  const changes: string[] = [];

  if (request.currentImage !== request.targetImage) {
    changes.push(`spec.template.spec.containers[0].image: ${request.currentImage} -> ${request.targetImage}`);
  }

  if (request.currentReplicas !== request.desiredReplicas) {
    changes.push(`spec.replicas: ${request.currentReplicas} -> ${request.desiredReplicas}`);
  }

  if (changes.length === 0) {
    changes.push("No manifest changes detected.");
  }

  return {
    mode: "dry-run",
    cluster: request.cluster,
    namespace: request.namespace,
    deployment: request.deployment,
    patchPreview: changes,
    rolloutSteps: [
      "Fetch current deployment",
      "Compare desired image and replicas",
      "Generate patch preview",
      "Stop before applying any live change",
    ],
    generatedAt: new Date().toISOString(),
  };
}

function buildInitialSnapshot(request: ChangeRequest) {
  return {
    view: "k8s-change-assistant",
    request,
    deploymentStatus: buildDeploymentStatus(request),
    pods: buildPods(request),
    events: buildEvents(request),
    summary: buildSummary(request),
    dryRun: buildDryRun(request),
    note: "This demo uses mock Kubernetes data. Replace the helper functions in server.ts with real Kubernetes API or kubectl calls.",
  };
}

function asTextToolResult(payload: unknown) {
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(payload, null, 2),
      },
    ],
  };
}

export function createServer(): McpServer {
  const server = new McpServer({
    name: "K8s Change Assistant MCP App",
    version: "1.0.0",
  });

  registerAppTool(
    server,
    "open-k8s-change-assistant",
    {
      title: "Open Kubernetes Change Assistant",
      description:
        "Open an interactive dry-run assistant for reviewing a Kubernetes deployment change.",
      inputSchema: {},
      _meta: { ui: { resourceUri } },
    },
    async () => asTextToolResult(buildInitialSnapshot(DEFAULT_REQUEST)),
  );

  registerAppResource(
    server,
    resourceUri,
    resourceUri,
    { mimeType: RESOURCE_MIME_TYPE },
    async () => {
      const html = await fs.readFile(path.join(DIST_DIR, "mcp-app.html"), "utf-8");
      return {
        contents: [{ uri: resourceUri, mimeType: RESOURCE_MIME_TYPE, text: html }],
      };
    },
  );

  server.registerTool(
    "get-deployment-status",
    {
      title: "Get deployment status",
      description: "Return mock deployment status for the selected Kubernetes deployment.",
      annotations: { readOnlyHint: true },
    },
    async (args: Record<string, unknown> = {}) => asTextToolResult(buildDeploymentStatus(normalizeRequest(args))),
  );

  server.registerTool(
    "get-pod-list",
    {
      title: "Get pod list",
      description: "Return mock pods for the selected Kubernetes deployment.",
      annotations: { readOnlyHint: true },
    },
    async (args: Record<string, unknown> = {}) => asTextToolResult(buildPods(normalizeRequest(args))),
  );

  server.registerTool(
    "get-recent-events",
    {
      title: "Get recent events",
      description: "Return mock recent Kubernetes events for the selected deployment.",
      annotations: { readOnlyHint: true },
    },
    async (args: Record<string, unknown> = {}) => asTextToolResult(buildEvents(normalizeRequest(args))),
  );

  server.registerTool(
    "generate-change-summary",
    {
      title: "Generate change summary",
      description: "Generate a short dry-run summary and risk checklist for the selected deployment change.",
      annotations: { readOnlyHint: true },
    },
    async (args: Record<string, unknown> = {}) => asTextToolResult(buildSummary(normalizeRequest(args))),
  );

  server.registerTool(
    "dry-run-change",
    {
      title: "Dry-run deployment change",
      description: "Create a mock dry-run patch preview for the selected deployment change.",
      annotations: { readOnlyHint: true },
    },
    async (args: Record<string, unknown> = {}) => asTextToolResult(buildDryRun(normalizeRequest(args))),
  );

  return server;
}
