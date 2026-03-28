# Vin's Questions — AI Infrastructure Setup: Research & Evaluation

> **Context:** This document evaluates the GitLessOps AI infrastructure stack including **kagent**, **kgateway (AI Gateway)**, **vLLM**, **llm-d**, **FastMCP**, and supporting Kubernetes-native tooling.

---

## 1. How could we handle 'agent got stuck' scenarios?

Stuck agents are a real operational concern in multi-step agentic workflows. The mitigation strategy is layered:

### Timeout at the Agent/Task level (kagent)

In kagent, each `Agent` resource can be configured with execution timeouts. If an agent exceeds its allotted time without completing, the controller marks it as failed and can trigger a retry or fallback:

```yaml
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: deployment-agent
spec:
  maxExecutionTime: "120s" # wall-clock timeout
  retryPolicy:
    maxRetries: 2
    backoffSeconds: 5
```

### Tool Call Timeouts

Individual MCP tool calls should define their own timeouts so a single stuck tool doesn't freeze the whole agent. FastMCP supports per-tool timeout annotations:

```python
@mcp.tool(timeout=30)
async def deploy_service(name: str) -> str:
    ...
```

### Kubernetes-level watchdogs

Since kagent runs Agents as Kubernetes resources, you can use:

- **`activeDeadlineSeconds`** on underlying Job/Pod resources
- **Liveness probes** on agent runner pods to detect deadlocks
- A **custom Kubernetes controller** watching Agent CRD status transitions and force-terminating stale ones

### Circuit Breaker at the LLM Gateway

At kgateway level, if an LLM backend is non-responsive, the circuit breaker trips and prevents new requests from piling up (see Q2).

### Recommended pattern

Implement a **supervisor agent** — a lightweight agent that monitors child agents via the kagent API, detects `Pending` states exceeding threshold, and issues `kubectl delete` or triggers the retry workflow.

---

## 2. Any automatic timeout / circuit breaker patterns from this framework?

### kgateway (Envoy AI Gateway)

kgateway is built on Envoy Proxy, which has native support for:

- **`timeout`** — per-route request timeout
- **`retryPolicy`** — automatic retries with exponential backoff on 5xx / connection failures
- **Outlier Detection (Circuit Breaker)** — ejects unhealthy upstream LLM endpoints automatically

Example `BackendLBPolicy` with circuit breaker:

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: BackendTrafficPolicy
metadata:
  name: llm-circuit-breaker
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: llm-route
  circuitBreaker:
    maxConnections: 100
    maxPendingRequests: 50
    maxRetries: 3
  timeout:
    request:
      timeout: 30s
```

### vLLM

vLLM exposes `/health` endpoint and supports request-level timeouts via the OpenAI-compatible API. At the infrastructure level, Kubernetes `readinessProbe` / `livenessProbe` on the vLLM pod acts as a circuit breaker at the pod scheduling layer.

### kagent

Currently kagent relies on Kubernetes-native timeout mechanisms (job deadlines, operator reconcile loops). Framework-level circuit breaker support is evolving — community contributions are active in this area.

---

## 3. How does kgateway handle model failover?

kgateway supports **multi-backend routing with priority-based failover** using Envoy's upstream cluster configuration.

### Traffic splitting and failover

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-failover
spec:
  rules:
    - backendRefs:
        - name: openai-backend
          port: 443
          weight: 100 # primary
        - name: claude-backend
          port: 443
          weight: 0 # standby failover
```

With `BackendTrafficPolicy` outlier detection, kgateway automatically ejects a failing backend and shifts traffic. For **active failover** (not just passive), you configure health-check-based routing:

```yaml
spec:
  healthCheck:
    passive:
      consecutiveErrors: 3
      interval: 10s
      baseEjectionTime: 30s
```

### AI Gateway-specific: Model Routing

The Envoy AI Gateway extension (part of kgateway's AI capabilities) understands LLM provider semantics — it can route based on model name in the request body:

```
POST /v1/chat/completions
{"model": "gpt-4o"} → routes to OpenAI
{"model": "claude-3-5-sonnet"} → routes to Anthropic
{"model": "llama-3.1-70b"} → routes to local vLLM
```

This enables seamless failover **at the model selector level**, not just the HTTP level.

---

## 4. Can we automatically switch from OpenAI → Claude → local model?

**Yes, this is a first-class use case for kgateway + Envoy AI Gateway.**

### Priority-based cascade failover

```yaml
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: LLMRoute
metadata:
  name: model-cascade
spec:
  rules:
    - matches:
        - model: "gpt-4o"
      backendRefs:
        - name: openai
          priority: 1 # try first
        - name: anthropic-claude
          priority: 2 # fallback
        - name: vllm-local
          priority: 3 # last resort
      failoverConditions:
        - statusCodes: [429, 500, 502, 503]
        - timeout: 15s
```

### What triggers the switch?

- HTTP 429 (rate limit) → immediate fallback
- HTTP 5xx (provider error) → fallback after N retries
- Timeout → fallback
- Budget exhausted (token quota) → fallback to cheaper/local model

### GitLessOps integration

In GitLessOps, you can encode the fallback policy as a Git-committed `LLMRoute` resource. A voice command like _"switch to local model"_ retags the OCI artifact → Flux reconciles → new `LLMRoute` applies. Zero manual kubectl.

---

## 5. Could we seamlessly handle response formats from these providers?

This is the **trickiest part** — providers differ in subtle but breaking ways.

### Where they differ

| Feature          | OpenAI                        | Anthropic Claude                 | vLLM (local)      |
| ---------------- | ----------------------------- | -------------------------------- | ----------------- |
| Tool call format | `tool_calls[]`                | `tool_use` blocks                | OpenAI-compatible |
| Streaming SSE    | `data: {...}`                 | `data: {...}` (different events) | OpenAI-compatible |
| Stop reason      | `finish_reason: "tool_calls"` | `stop_reason: "tool_use"`        | OpenAI-compatible |
| System prompt    | `messages[0].role: system`    | `system: "..."` top-level        | OpenAI-compatible |

### Solutions

**Option A: kgateway response transformation (recommended)**
Envoy's `HTTPRoute` supports response body transformation via `ExtProc` (External Processing) filter. You deploy a lightweight transformer sidecar that normalizes all responses to OpenAI format:

```
[Claude response] → ExtProc transformer → [OpenAI format] → agent
```

**Option B: LiteLLM as a normalization layer**
LiteLLM is purpose-built for this — it proxies all major providers and outputs a unified OpenAI-compatible format. Deploy it as a service behind kgateway:

```
kgateway → LiteLLM → OpenAI / Anthropic / vLLM
```

**Option C: Provider-aware agent tooling**
kagent and most modern agent frameworks (LangChain, CrewAI, Google ADK) abstract provider differences at the SDK level. If all agent-LLM communication goes through such a framework, format differences are handled transparently.

**Recommendation:** Use **LiteLLM** behind kgateway for the normalization layer — least complexity, battle-tested, maintains the OpenAI interface your agents already use.

---

## 6. Can we version the agents built from kagent?

**Yes — and this aligns perfectly with GitLessOps.**

### GitOps versioning (primary approach)

Every `Agent` CRD manifest is a YAML file in Git. Versioning = Git commits + tags:

```
agents/
  deployment-agent/
    v1.0.0/
      agent.yaml        # kagent Agent CRD
      toolserver.yaml   # MCP ToolServer reference
    v1.1.0/
      agent.yaml        # updated system prompt, new tools
```

**Rollback** = `git revert` or `git checkout v1.0.0` → Flux reconciles → previous agent version restored.

### OCI artifact versioning

Agent configurations (system prompts, tool lists, model parameters) can be packaged as OCI artifacts and pushed to a container registry:

```
ghcr.io/org/agents/deployment-agent:v1.0.0
ghcr.io/org/agents/deployment-agent:v1.1.0
ghcr.io/org/agents/deployment-agent:latest
```

A `Kustomization` or `OCIRepository` Flux source pins a specific tag — this is exactly how GitLessOps manages app versions.

### Semantic versioning convention

Recommended tagging:

- `v<major>.<minor>.<patch>` — e.g., `v1.2.0`
- `<environment>-latest` — e.g., `prod-latest`, `staging-latest`
- Immutable tags for prod deployments

---

## 7. Any blue/green or canary deployment patterns for agents?

**Absolutely — Kubernetes gives us all the primitives needed.**

### Blue/Green for agents

Deploy two versions simultaneously, switch traffic atomically:

```yaml
# Blue (current prod)
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: deployment-agent-blue
  labels:
    version: blue
spec:
  modelConfig:
    model: gpt-4o
  systemPrompt: "v1 prompt..."

---
# Green (new version)
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: deployment-agent-green
  labels:
    version: green
spec:
  modelConfig:
    model: gpt-4o
  systemPrompt: "v2 prompt..."
```

Switch via `HTTPRoute` weight: set green to 100%, blue to 0%. Instant rollback = swap weights back.

### Canary for agents

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
spec:
  rules:
    - backendRefs:
        - name: agent-v1-service
          weight: 90 # stable
        - name: agent-v2-service
          weight: 10 # canary — 10% of requests
```

Gradually increase canary weight while monitoring:

- Response quality metrics (custom, via evaluation pipeline)
- Latency percentiles
- Error rates (5xx from LLM)
- Token usage (cost)

### GitLessOps voice-driven canary

In GitLessOps: voice command _"promote agent v2 to 25%"_ → GitHub Actions updates `weight` in Kustomize patch → Flux reconciles → canary shifts. Full audit trail in Git.

---

## 8. What's the FastMCP-Python framework?

**FastMCP** is a high-level Python framework for building **MCP (Model Context Protocol) servers** — the interface through which AI agents call external tools.

### What it does

MCP defines a standard protocol for LLMs to discover and invoke tools. FastMCP makes building those servers as simple as writing a Python function:

```python
from fastmcp import FastMCP

mcp = FastMCP("kubernetes-tools")

@mcp.tool()
async def get_pod_logs(namespace: str, pod_name: str) -> str:
    """Retrieve logs from a Kubernetes pod."""
    # kubectl logs implementation
    return logs

@mcp.resource("k8s://namespaces")
async def list_namespaces() -> list[str]:
    return ["prod", "staging", "dev"]

if __name__ == "__main__":
    mcp.run()
```

### Key features

- **Decorator-based API** — `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`
- **Automatic schema generation** — type hints → JSON Schema for tool parameters
- **Transport support** — stdio, HTTP/SSE, WebSocket
- **Auth** — OAuth2/API key integration
- **Testing utilities** — in-process test client
- **FastAPI lineage** — familiar patterns for Python web developers

### In GitLessOps context

FastMCP is used to expose Kubernetes operations (deploy, rollback, scale) as MCP tools that kagent calls. The voice-to-deployment pipeline: speech → STT → LLM (kagent) → MCP tool (FastMCP) → kubectl/Flux action.

---

## 9. Is FastMCP the easiest path to MCP?

**For Python developers: yes, it is the current gold standard for ease of use.**

### Comparison of MCP server options

| Approach                 | Language            | Complexity  | Best for                                   |
| ------------------------ | ------------------- | ----------- | ------------------------------------------ |
| **FastMCP**              | Python              | ⭐ Low      | Python devs, rapid prototyping, production |
| MCP SDK (official)       | Python / TypeScript | ⭐⭐ Medium | Full control, custom transports            |
| mcp-go                   | Go                  | ⭐⭐ Medium | Go shops, performance-critical             |
| Manual HTTP/SSE          | Any                 | ⭐⭐⭐ High | Existing APIs, brownfield                  |
| Claude Desktop built-ins | N/A                 | ⭐ Low      | Local dev/demo only                        |

### Why FastMCP wins for GitLessOps

1. **Decorator simplicity** — wrapping existing Python Kubernetes client code is trivial
2. **Auto-discovery** — tools are automatically surfaced to agents via the MCP handshake
3. **Kubernetes-deployable** — runs as a standard Python HTTP service in a container
4. **kagent native** — kagent's `ToolServer` resource points directly at a FastMCP HTTP endpoint
5. **Active community** — fastest-growing MCP framework as of early 2025

### Caveat

If your tooling is already in Go (e.g., existing Kubernetes controllers), **mcp-go** or a thin HTTP wrapper may be more natural. FastMCP is the easiest path, not the only path.

---

## 10–13. FinOps: Cost Control, Token Limits, Per-Agent Budgets

These questions are grouped because they form a coherent FinOps strategy.

### Q10: How much control can I have?

**Full control — but you must assemble it from multiple layers.**

There is no single "AI FinOps" toggle. Control is available at:

| Layer       | Mechanism                                                         | Granularity           |
| ----------- | ----------------------------------------------------------------- | --------------------- |
| LLM API     | Provider-level quotas (OpenAI Usage Limits, Anthropic Workspaces) | Per API key           |
| kgateway    | Token counting headers, rate limiting, budget enforcement         | Per route / per agent |
| vLLM        | `--max-model-len`, request queue limits                           | Per model deployment  |
| Application | Per-agent token budgets in system prompt / config                 | Per agent             |
| Kubernetes  | Resource quotas, namespace limits                                 | Per namespace         |

### Q11: Token-level and per-agent control

**Token-level tracking:**
kgateway's AI Gateway extension intercepts responses and reads `usage.total_tokens` from the LLM response. This data can be:

- Emitted as Prometheus metrics: `llm_tokens_total{agent="deployment-agent", model="gpt-4o"}`
- Used for rate limiting: block requests once hourly token budget is consumed

```yaml
# kgateway rate limit by tokens (conceptual)
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: BackendTrafficPolicy
spec:
  rateLimit:
    global:
      rules:
        - limit:
            requests: 10000 # token-equivalent proxy
            unit: Hour
          headers:
            - name: X-Agent-ID
              type: Distinct # per-agent limit
```

**Per-agent tracking:**
Tag every LLM request with `X-Agent-ID` header at the kagent level. kgateway reads this header for routing decisions and metric labeling.

### Q12: Custom cost controls

**Yes — several approaches:**

**1. Token budget enforcement in system prompt:**

```
System: You are a deployment agent. You have a budget of 2000 tokens per task.
If you approach 1800 tokens, summarize and conclude immediately.
```

**2. Middleware / ExtProc filter in kgateway:**
Build a lightweight sidecar (Python/Go) that:

- Tracks cumulative tokens per agent per time window in Redis
- Returns HTTP 429 when budget exceeded
- kgateway routes all LLM traffic through this filter

**3. LiteLLM budget manager:**
LiteLLM has a built-in budget manager:

```python
from litellm import budget_manager
budget_manager.create_budget(
    project_name="deployment-agent",
    total_budget=10.00,   # USD
    duration="monthly"
)
```

### Q13: Per-agent budgets and token depth limits

**Per-agent budget pattern:**

```yaml
# ConfigMap per agent with budget
apiVersion: v1
kind: ConfigMap
metadata:
  name: deployment-agent-budget
data:
  monthly_usd_limit: "50"
  hourly_token_limit: "100000"
  max_tokens_per_request: "4096"
  max_tool_call_depth: "10"
```

**Max tool call depth** is critical for preventing infinite loops:

```python
# In agent runner
MAX_TOOL_CALL_DEPTH = int(os.environ.get("MAX_TOOL_CALL_DEPTH", 10))

if tool_call_count >= MAX_TOOL_CALL_DEPTH:
    raise AgentDepthLimitExceeded(f"Exceeded {MAX_TOOL_CALL_DEPTH} tool calls")
```

**Grafana + Prometheus dashboard** should track per-agent:

- `llm_tokens_total` (with agent label)
- `llm_cost_usd_total` (calculated from token count × model price)
- `llm_tool_calls_total`

---

## 14. Is vLLM suitable for agents with many back-and-forth tool calls?

**Short answer: Yes, but with important caveats.**

### vLLM strengths

- **Continuous batching** — dynamically batches concurrent requests; good for multiple agents running in parallel
- **PagedAttention** — efficient KV cache management; handles long contexts better than naive implementations
- **OpenAI-compatible API** — drop-in for agent frameworks expecting OpenAI endpoints
- **High throughput** — optimized for serving many requests/second on GPU

### The challenge with agentic workloads

Agentic tool-call loops have a specific access pattern:

- **Many short, sequential requests** per agent (one round-trip per tool call)
- **Low batch size per agent** — each agent sends 1 request at a time
- **Long context accumulation** — every tool result is appended to context

vLLM's continuous batching _helps_ when many agents run concurrently (aggregated throughput). But for a **single agent** doing 15 sequential tool calls, vLLM doesn't provide latency advantages over a simpler serving setup.

### Recommendation

| Use case                                   | vLLM fit                             |
| ------------------------------------------ | ------------------------------------ |
| Many agents running concurrently           | ✅ Excellent — batching shines       |
| Single agent, deep tool call chain         | ⚠️ Acceptable — no special advantage |
| Single-shot inference (RAG, summarization) | ✅ Excellent                         |
| Streaming responses during tool loops      | ✅ Supported                         |

**For GitLessOps:** With multiple concurrent voice-triggered deployments (multiple users/agents), vLLM is the right choice. For single-user sequential debugging sessions, a simpler Ollama or llama.cpp setup may have lower operational overhead.

**Optimize vLLM for agentic use:**

- Use `--enable-prefix-caching` — caches shared prompt prefixes (system prompt) across requests in the same session, reducing TTFT
- Set `--max-num-seqs` appropriately for expected agent concurrency

---

## 15. llm-d's scheduler — does it help when an agent makes 15 LLM calls?

**Yes, and this is precisely the use case llm-d was designed for.**

### What is llm-d?

**llm-d** (LLM Distributed) is a Kubernetes-native distributed LLM inference scheduler, originally developed at Red Hat / upstream Kubernetes community. It extends the standard Kubernetes scheduler with LLM-specific awareness.

### The problem with 15 sequential LLM calls

In a naive setup, each of the 15 calls goes to an arbitrary vLLM pod. The KV cache (conversation context) from call 1 is on Pod A; call 2 lands on Pod B — cache miss, full re-prefill. This is:

- **Slow** — re-prefilling a growing context on every call
- **Expensive** — wasted compute on repeated context processing

### How llm-d solves this

**KV Cache-aware routing:**
llm-d's scheduler tracks which pods hold KV cache for which request sessions. It routes call 2, 3, ... 15 to the **same pod** that handled call 1, achieving cache hits:

```
Agent session "deploy-abc123":
  Call 1  → Pod A  (cache miss, prefill 500 tokens)
  Call 2  → Pod A  (cache HIT — only prefill new 50 tokens)
  Call 3  → Pod A  (cache HIT — only prefill new 50 tokens)
  ...
  Call 15 → Pod A  (cache HIT — massive latency savings)
```

**Disaggregated prefill/decode:**
For long-context agentic sessions, llm-d can separate the prefill computation (expensive) from the decode (token generation), assigning them to different GPU types — prefill to high-compute GPUs, decode to memory-bandwidth-optimized GPUs.

### Practical impact for 15-call agent

| Without llm-d               | With llm-d                   |
| --------------------------- | ---------------------------- |
| 15× full context re-prefill | 1× prefill + 14× incremental |
| ~15× TTFT penalty           | ~1–2× TTFT penalty           |
| Random pod routing          | Session-affinity routing     |

### GitLessOps relevance

For the GitLessOps deployment agent that might do: _plan → check cluster → check git status → generate manifests → validate → apply_ — that's 6-10 LLM calls. llm-d's session-affinity routing makes this workflow significantly faster and cheaper on local GPU infrastructure.

**Note:** llm-d is production-ready on GKE and upstream Kubernetes as of 2025, and integrates with vLLM as the inference backend. Deploying it in your GKE + on-prem vSphere environment is viable with the `llm-d-deployer` Helm chart.

---

## Summary Table

| #   | Question                        | Key Technology                        | Complexity |
| --- | ------------------------------- | ------------------------------------- | ---------- |
| 1   | Agent stuck handling            | kagent timeouts + K8s watchdog        | Medium     |
| 2   | Circuit breaker                 | kgateway (Envoy) BackendTrafficPolicy | Low        |
| 3   | Model failover                  | kgateway LLMRoute priority            | Low        |
| 4   | Auto switch OpenAI→Claude→local | kgateway + LLMRoute cascade           | Low        |
| 5   | Response format normalization   | LiteLLM proxy / ExtProc transformer   | Medium     |
| 6   | Agent versioning                | GitOps (Flux) + OCI tags              | Low        |
| 7   | Blue/green / canary             | HTTPRoute weights + GitLessOps        | Medium     |
| 8   | FastMCP-Python                  | FastMCP framework                     | Low        |
| 9   | Easiest path to MCP             | FastMCP (yes, for Python)             | Low        |
| 10  | FinOps control scope            | Multi-layer: gateway + app + provider | Medium     |
| 11  | Token/per-agent limits          | kgateway metrics + headers            | Medium     |
| 12  | Custom cost controls            | LiteLLM budget manager / ExtProc      | Medium     |
| 13  | Per-agent budgets               | ConfigMap + Prometheus + depth limits | Medium     |
| 14  | vLLM for agentic loops          | Yes + prefix caching recommended      | Low        |
| 15  | llm-d scheduler value           | High — KV cache session affinity      | High       |

---

_Prepared as part of the DevOps & Kubernetes Practical Intensive+ certification final work._
_Stack: kagent · kgateway (Envoy AI Gateway) · vLLM · llm-d · FastMCP · Flux CD · GitLessOps_
