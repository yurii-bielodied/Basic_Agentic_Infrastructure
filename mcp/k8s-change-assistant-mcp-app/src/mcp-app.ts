import { App } from "@modelcontextprotocol/ext-apps";

type AppPayload = {
  note?: string;
  request?: RequestState;
  deploymentStatus?: Record<string, unknown>;
  pods?: PodInfo[];
  events?: EventInfo[];
  summary?: SummaryInfo;
  dryRun?: DryRunInfo;
};

type RequestState = {
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
  type: string;
  reason: string;
  object: string;
  age: string;
  message: string;
};

type SummaryInfo = {
  title: string;
  summary: string;
  risks: string[];
  recommendedChecks: string[];
  approvalSuggestion: string;
  generatedAt: string;
};

type DryRunInfo = {
  mode: string;
  cluster: string;
  namespace: string;
  deployment: string;
  patchPreview: string[];
  rolloutSteps: string[];
  generatedAt: string;
};

const app = new App({ name: "K8s Change Assistant", version: "1.0.0" });

const clusterInput = document.getElementById("cluster") as HTMLInputElement;
const namespaceInput = document.getElementById("namespace") as HTMLInputElement;
const deploymentInput = document.getElementById("deployment") as HTMLInputElement;
const currentImageInput = document.getElementById("currentImage") as HTMLInputElement;
const targetImageInput = document.getElementById("targetImage") as HTMLInputElement;
const currentReplicasInput = document.getElementById("currentReplicas") as HTMLInputElement;
const desiredReplicasInput = document.getElementById("desiredReplicas") as HTMLInputElement;

const noteText = document.getElementById("noteText") as HTMLParagraphElement;
const statusBadges = document.getElementById("statusBadges") as HTMLDivElement;
const deploymentStatus = document.getElementById("deploymentStatus") as HTMLDListElement;
const podsContainer = document.getElementById("podsContainer") as HTMLDivElement;
const eventsContainer = document.getElementById("eventsContainer") as HTMLDivElement;
const summaryContainer = document.getElementById("summaryContainer") as HTMLDivElement;
const dryRunContainer = document.getElementById("dryRunContainer") as HTMLDivElement;

const refreshAllBtn = document.getElementById("refreshAllBtn") as HTMLButtonElement;
const statusBtn = document.getElementById("statusBtn") as HTMLButtonElement;
const podsBtn = document.getElementById("podsBtn") as HTMLButtonElement;
const eventsBtn = document.getElementById("eventsBtn") as HTMLButtonElement;
const summaryBtn = document.getElementById("summaryBtn") as HTMLButtonElement;
const dryRunBtn = document.getElementById("dryRunBtn") as HTMLButtonElement;

function getRequestState(): RequestState {
  return {
    cluster: clusterInput.value.trim(),
    namespace: namespaceInput.value.trim(),
    deployment: deploymentInput.value.trim(),
    currentImage: currentImageInput.value.trim(),
    targetImage: targetImageInput.value.trim(),
    currentReplicas: Number(currentReplicasInput.value || 1),
    desiredReplicas: Number(desiredReplicasInput.value || 1),
  };
}

function updateForm(request?: RequestState): void {
  if (!request) {
    return;
  }

  clusterInput.value = request.cluster;
  namespaceInput.value = request.namespace;
  deploymentInput.value = request.deployment;
  currentImageInput.value = request.currentImage;
  targetImageInput.value = request.targetImage;
  currentReplicasInput.value = String(request.currentReplicas);
  desiredReplicasInput.value = String(request.desiredReplicas);
}

function parseToolJson(result: { content?: Array<{ type: string; text?: string }> }): unknown {
  const text = result.content?.find((item) => item.type === "text")?.text;
  if (!text) {
    throw new Error("Tool returned no text payload.");
  }
  return JSON.parse(text);
}

async function callJsonTool<T>(name: string, args: Record<string, unknown>): Promise<T> {
  const result = await app.callServerTool({ name, arguments: args });
  return parseToolJson(result) as T;
}

function renderBadges(status: Record<string, unknown>): void {
  const changes = (status.changesDetected ?? {}) as Record<string, boolean>;
  const badges = [
    `<span class="badge success">availableReplicas: ${String(status.availableReplicas ?? "-")}</span>`,
    `<span class="badge success">readyReplicas: ${String(status.readyReplicas ?? "-")}</span>`,
    `<span class="badge ${changes.imageWillChange ? "warn" : "success"}">image change: ${changes.imageWillChange ? "yes" : "no"}</span>`,
    `<span class="badge ${changes.replicasWillChange ? "warn" : "success"}">replica change: ${changes.replicasWillChange ? "yes" : "no"}</span>`,
  ];
  statusBadges.innerHTML = badges.join("");
}

function renderDeploymentStatus(status?: Record<string, unknown>): void {
  if (!status) {
    deploymentStatus.innerHTML = `<div class="empty">No deployment status loaded.</div>`;
    statusBadges.innerHTML = "";
    return;
  }

  renderBadges(status);
  const rows: Array<[string, string]> = [
    ["Cluster", String(status.cluster ?? "-")],
    ["Namespace", String(status.namespace ?? "-")],
    ["Deployment", String(status.deployment ?? "-")],
    ["Current image", String(status.currentImage ?? "-")],
    ["Target image", String(status.targetImage ?? "-")],
    ["Current replicas", String(status.currentReplicas ?? "-")],
    ["Desired replicas", String(status.desiredReplicas ?? "-")],
    ["Observed generation", String(status.observedGeneration ?? "-")],
    ["Generated at", String(status.generatedAt ?? "-")],
  ];

  deploymentStatus.innerHTML = rows
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
}

function renderPods(pods?: PodInfo[]): void {
  if (!pods || pods.length === 0) {
    podsContainer.innerHTML = `<div class="empty">No pods loaded yet.</div>`;
    return;
  }

  const rows = pods
    .map(
      (pod) => `
        <tr>
          <td>${escapeHtml(pod.name)}</td>
          <td>${escapeHtml(pod.ready)}</td>
          <td>${escapeHtml(pod.status)}</td>
          <td>${pod.restarts}</td>
          <td>${escapeHtml(pod.age)}</td>
          <td>${escapeHtml(pod.node)}</td>
        </tr>`,
    )
    .join("");

  podsContainer.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Ready</th>
          <th>Status</th>
          <th>Restarts</th>
          <th>Age</th>
          <th>Node</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderEvents(events?: EventInfo[]): void {
  if (!events || events.length === 0) {
    eventsContainer.innerHTML = `<div class="empty">No events loaded yet.</div>`;
    return;
  }

  eventsContainer.innerHTML = `
    <ul>
      ${events
        .map(
          (event) => `
            <li>
              <strong>${escapeHtml(event.type)} / ${escapeHtml(event.reason)}</strong>
              — ${escapeHtml(event.object)} (${escapeHtml(event.age)})<br />
              <span>${escapeHtml(event.message)}</span>
            </li>`,
        )
        .join("")}
    </ul>`;
}

function renderSummary(summary?: SummaryInfo): void {
  if (!summary) {
    summaryContainer.innerHTML = `<div class="empty">No summary generated yet.</div>`;
    return;
  }

  summaryContainer.innerHTML = `
    <div class="grid">
      <div><strong>${escapeHtml(summary.title)}</strong></div>
      <div>${escapeHtml(summary.summary)}</div>
      <div>
        <strong>Risks</strong>
        <ul>${summary.risks.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")}</ul>
      </div>
      <div>
        <strong>Recommended checks</strong>
        <ul>${summary.recommendedChecks.map((check) => `<li>${escapeHtml(check)}</li>`).join("")}</ul>
      </div>
      <div><strong>Approval suggestion:</strong> ${escapeHtml(summary.approvalSuggestion)}</div>
      <div class="muted">Generated at: ${escapeHtml(summary.generatedAt)}</div>
    </div>`;
}

function renderDryRun(dryRun?: DryRunInfo): void {
  if (!dryRun) {
    dryRunContainer.innerHTML = `<div class="empty">No dry-run executed yet.</div>`;
    return;
  }

  dryRunContainer.innerHTML = `
    <div class="grid">
      <div><strong>Mode:</strong> ${escapeHtml(dryRun.mode)}</div>
      <div><strong>Target:</strong> ${escapeHtml(dryRun.cluster)}/${escapeHtml(dryRun.namespace)}/${escapeHtml(dryRun.deployment)}</div>
      <div>
        <strong>Patch preview</strong>
        <pre>${escapeHtml(dryRun.patchPreview.join("\n"))}</pre>
      </div>
      <div>
        <strong>Workflow</strong>
        <ul>${dryRun.rolloutSteps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ul>
      </div>
      <div class="muted">Generated at: ${escapeHtml(dryRun.generatedAt)}</div>
    </div>`;
}

function renderPayload(payload: AppPayload): void {
  updateForm(payload.request);
  noteText.textContent = payload.note ?? "Ready.";
  renderDeploymentStatus(payload.deploymentStatus);
  renderPods(payload.pods);
  renderEvents(payload.events);
  renderSummary(payload.summary);
  renderDryRun(payload.dryRun);
}

async function refreshAll(): Promise<void> {
  const request = getRequestState();
  noteText.textContent = "Refreshing deployment status, pods, events, summary, and dry-run...";

  const [status, pods, events, summary, dryRun] = await Promise.all([
    callJsonTool<Record<string, unknown>>("get-deployment-status", request),
    callJsonTool<PodInfo[]>("get-pod-list", request),
    callJsonTool<EventInfo[]>("get-recent-events", request),
    callJsonTool<SummaryInfo>("generate-change-summary", request),
    callJsonTool<DryRunInfo>("dry-run-change", request),
  ]);

  renderPayload({
    note: "Context refreshed from server tools.",
    request,
    deploymentStatus: status,
    pods,
    events,
    summary,
    dryRun,
  });
}

function wireAction(button: HTMLButtonElement, action: () => Promise<void>): void {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await action();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      noteText.textContent = `Error: ${message}`;
    } finally {
      button.disabled = false;
    }
  });
}

wireAction(refreshAllBtn, refreshAll);
wireAction(statusBtn, async () => {
  const request = getRequestState();
  const status = await callJsonTool<Record<string, unknown>>("get-deployment-status", request);
  renderDeploymentStatus(status);
  noteText.textContent = "Deployment status refreshed.";
});
wireAction(podsBtn, async () => {
  const request = getRequestState();
  const pods = await callJsonTool<PodInfo[]>("get-pod-list", request);
  renderPods(pods);
  noteText.textContent = "Pod list refreshed.";
});
wireAction(eventsBtn, async () => {
  const request = getRequestState();
  const events = await callJsonTool<EventInfo[]>("get-recent-events", request);
  renderEvents(events);
  noteText.textContent = "Recent events refreshed.";
});
wireAction(summaryBtn, async () => {
  const request = getRequestState();
  const summary = await callJsonTool<SummaryInfo>("generate-change-summary", request);
  renderSummary(summary);
  noteText.textContent = "Risk summary generated.";
});
wireAction(dryRunBtn, async () => {
  const request = getRequestState();
  const dryRun = await callJsonTool<DryRunInfo>("dry-run-change", request);
  renderDryRun(dryRun);
  noteText.textContent = "Dry-run preview generated.";
});

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

app.ontoolresult = (result) => {
  try {
    const payload = parseToolJson(result) as AppPayload;
    renderPayload(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    noteText.textContent = `Failed to parse initial tool result: ${message}`;
  }
};

app.connect();
