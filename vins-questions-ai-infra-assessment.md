# Vin's Questions — assessment of my AI infrastructure setup

## Scope and assumptions

This assessment is written for a Kubernetes-based setup centered around **kagent** for agents, **kmcp/FastMCP** for MCP servers, **kgateway/agentgateway** for LLM routing and control, and optional **vLLM** or **llm-d** for self-hosted inference.

The key conclusion is this:

- **kagent** is strong for agent lifecycle, Kubernetes-native deployment, MCP/A2A connectivity, and composition.
- **kgateway / agentgateway** is where most of the **runtime resilience, provider routing, failover, traffic shaping, and cost governance** should live.
- **FastMCP** is the easiest Python path to MCP.
- **vLLM** is a strong self-hosted inference engine for agent workloads too, but it is **not** the agent orchestrator.
- **llm-d** becomes interesting when self-hosted inference grows beyond a simple single-endpoint model server and you want smarter routing, better cache locality, and higher throughput.

---

## 1) How could we handle “agent got stuck” scenarios?

There is **no single documented “unstick agent” primitive** in kagent that solves every kind of stall end-to-end. In practice, the right design is a **layered timeout and recovery model**:

1. **Agent runtime guardrails**  
   For BYO agents, put hard limits into the agent framework itself: max iterations, max tool hops, max wall-clock time, and clear cancellation handling. This is especially important because kagent BYO mode gives you full control over the agent logic, which also means loop protection is largely your responsibility.

2. **Tool and MCP deadlines**  
   For remote MCP tools, kagent exposes `timeout` and `sseReadTimeout` on `RemoteMCPServer`. Use these aggressively for network-bound tools and long-lived streams.

3. **Gateway-side resilience**  
   Put request timeouts, per-try timeouts, retries, and circuit breakers in **kgateway**. That prevents one slow or broken upstream from hanging the whole agent flow.

4. **Context control**  
   Some “stuck” situations are really context bloat or degraded reasoning over long sessions. Kagent supports **context compaction** with `tokenThreshold`, `compactionInterval`, overlap retention, and an optional summarizer model.

### Recommended pattern

For production, I would treat “agent stuck” as an **operational SLO problem**, not just a prompting problem:

- set per-tool deadlines,
- set end-to-end request deadlines,
- cap agent loop depth in the BYO runtime,
- make tools idempotent where possible,
- emit traces/logs for each tool hop,
- return a graceful fallback such as _“The agent could not complete the workflow in time; partial results are available.”_

### Practical verdict

**Yes, this can be handled well, but mostly by combining kagent + kgateway + runtime policies.** I would not rely on one framework feature alone.

---

## 2) Any automatic timeout / circuit breaker patterns coming out from this framework?

### What exists today

- **kagent**: documented timeout controls for remote MCP servers (`timeout`, `sseReadTimeout`).
- **kgateway**: documented support for **request timeouts**, **per-try timeouts**, **retries**, and **circuit breakers**.

### What does not appear to be first-class

I did **not** find a documented kagent-native, end-to-end “agent circuit breaker policy” that automatically detects multi-step agent failure patterns across model calls, tool calls, and downstream services as one unified policy object.

### Conclusion

So the answer is:

- **Yes for the network and provider layers** — mainly through kgateway.
- **Partly for tool/MCP connectivity** — through kagent MCP timeout fields.
- **No single built-in universal agent circuit breaker** — you still need platform design and BYO runtime controls.

---

## 3) How does kgateway handle model failover?

kgateway’s **agentgateway** supports **model failover through priority groups**.

- You can define multiple providers/models inside an `AgentgatewayBackend`.
- The gateway evaluates groups in priority order.
- Inside the same group, backends are load balanced with **Power of Two Choices (P2C)**, using health, latency, and current load.
- If the preferred group fails or becomes unhealthy, traffic falls back to the next group.

This works for:

- failover between models from the **same provider**, and
- failover **across different providers**.

### Practical verdict

This is a strong point of the stack. It is one of the cleanest ways to keep agent traffic alive when a preferred model becomes unavailable, slow, or too expensive.

---

## 4) Can we automatically switch from OpenAI to Claude to local model?

**Yes.**

Agentgateway explicitly documents:

- **cross-provider failover**, including OpenAI and Anthropic, and
- support for **OpenAI-compatible providers**, including **vLLM, Ollama, LM Studio, and llama.cpp**.

That means a realistic fallback chain can look like this:

1. OpenAI primary model
2. Claude fallback model
3. local/self-hosted OpenAI-compatible endpoint (for example vLLM or Ollama)

### Important nuance

The cleanest design is to expose the local model through an **OpenAI-compatible API**. That minimizes application changes and makes routing much simpler.

### Practical verdict

**Yes — this is absolutely viable, and kgateway/agentgateway is the right layer to do it.**

---

## 5) Could we seamlessly handle the response formats from these providers?

### Mostly yes — but not “perfectly universal”

Agentgateway’s LLM layer is designed around a **unified API surface**, especially OpenAI-compatible access. It documents native support or translation support across providers such as OpenAI, Anthropic, Bedrock, Gemini, and Vertex AI.

A very useful detail is that **Anthropic can be exposed behind `/v1/chat/completions`**, even though Anthropic’s native endpoint is `/v1/messages`.

### The limitation

The docs make an important distinction:

- **Native support** means the provider already matches the API and unknown fields are more likely to pass through.
- **Translation support** means agentgateway maps one format to another, so support is limited to fields the gateway already knows about.

So the real answer is:

- **Yes for the common operational path** — chat, streaming, many provider integrations, and common fields.
- **Not fully seamless for every provider-specific feature forever** — especially when providers add new fields faster than the translation layer is updated.

### Practical verdict

For most productized agent use cases, response normalization is good enough. For bleeding-edge provider features, keep an escape hatch for provider-native endpoints or provider-specific routes.

---

## 6) Can we version the agents built from kagent?

### Yes operationally; partly as platform metadata

Kagent BYO agents are deployed from a **container image** defined in the `Agent` resource. That means the most practical versioning model is:

- container image tags/digests,
- Git tags/commits,
- Helm values or GitOps manifests,
- environment promotion across dev/stage/prod.

Kagent’s A2A agent card also includes a **`version` field**, but in the documented BYO example it is shown as empty by default. That suggests versioning is not yet a strong first-class release-management workflow by itself; it is mostly something you should enforce through your CI/CD and delivery process.

### Recommended approach

Use:

- immutable image digests,
- semantic tags for human readability,
- GitOps promotion,
- separate `Agent` manifests per environment,
- release notes for prompt/model/tool changes.

### Practical verdict

**Yes, agents are versionable, but the real versioning discipline comes from Kubernetes/GitOps/container delivery practices rather than a dedicated kagent release abstraction.**

---

## 7) Any blue/green or canary deployment patterns for agents?

### Yes — but mostly at the Kubernetes delivery layer

Kagent agents are Kubernetes-managed workloads, so standard progressive delivery patterns apply:

- rolling updates,
- **blue/green**,
- **canary**,
- weighted routing,
- header-based routing,
- Argo Rollouts.

This is not just theoretical:

- kgateway documents **traffic splitting** and weighted routing patterns that are useful for canary and A/B testing,
- kgateway also has documented examples/blog material for **Argo Rollouts canary deployments**,
- kagent even has an **argo-rollouts-conversion-agent** in its registry that focuses on converting Deployments into Rollouts using blue/green or canary strategy.

### Recommended agent rollout pattern

For agent changes, I would separate them into two categories:

1. **Safe infrastructure changes**: image update, resource tuning, sidecar changes  
   → normal rollout or canary.
2. **Behavioral changes**: prompt changes, tool changes, model changes  
   → canary with shadow traffic or controlled traffic split, because behavior changes can be more dangerous than code changes.

### Practical verdict

**Yes. Progressive delivery is very achievable, but it is mainly implemented through Kubernetes + kgateway + Argo Rollouts, not as a kagent-only feature.**

---

## 8) What’s the `fastmcp-python` framework mentioned?

There are two closely related things here:

1. The **official MCP Python SDK**, whose docs still show the `FastMCP` class via `from mcp.server.fastmcp import FastMCP`.
2. The standalone **FastMCP 2.0** project (`fastmcp-python`), which describes itself as the actively maintained framework and says FastMCP 1.0 was incorporated into the official MCP Python SDK in 2024.

### Interpretation

So when someone says **“fastmcp-python”**, they usually mean the broader FastMCP ecosystem/project, not only the minimal class exposed in the official SDK.

FastMCP focuses on making MCP development much easier by handling:

- tool declaration,
- schema generation,
- clients,
- auth,
- testing,
- composition/proxying,
- deployment-oriented patterns.

### Practical verdict

It is a very credible answer to “how do I build MCP servers in Python without fighting the protocol?”

---

## 9) Is it the easiest path to MCP?

### For Python: yes, usually

Both the official MCP docs and the kmcp quickstart strongly point in that direction:

- the official build-server tutorial uses **FastMCP**,
- the kmcp quickstart tells you to spin up your **first FastMCP Python server**,
- FastMCP auto-generates tool definitions from **type hints and docstrings**, which lowers boilerplate a lot.

### Caveat

If your team is strongly Go-centric, **MCP Go** may be a better fit operationally. The kmcp quickstart explicitly mentions MCP Go as an alternative.

### Practical verdict

- **Easiest path in Python**: FastMCP.
- **Easiest path overall**: depends on the team’s main language and runtime constraints.

If the goal is _fastest path from idea to working MCP server on Kubernetes_, FastMCP + kmcp is probably the best route in this ecosystem.

---

## 10) About FinOps: how much control can I have?

A lot — but most of it lives in **agentgateway**, not directly in the agent definition.

Agentgateway documents several governance building blocks:

- API key management,
- **virtual key style** patterns,
- **per-key token budgets**,
- **rate limiting**,
- **cost tracking**,
- token usage metrics,
- per-user usage breakdown,
- logs and observability.

### Practical verdict

For FinOps, this stack is viable if you treat the gateway as the **control plane for spend**, and agents as consumers behind it.

---

## 11) Token level / per-agent level

### Token level

**Yes.** Agentgateway exposes token usage metrics such as `agentgateway_gen_ai_client_token_usage`, including provider/model dimensions and request vs response token types.

### Per-agent level

I did **not** find a documented, first-class kagent field that says “this agent has a budget of X dollars or Y tokens per day.”

However, you can achieve effective per-agent governance by assigning each agent one of the following:

- a dedicated API key / virtual key,
- a dedicated route,
- a dedicated header/user identity,
- a dedicated model alias,
- a dedicated gateway policy attachment.

That gives you **practical per-agent cost control**, even if the primitive is technically implemented at the gateway layer.

### Practical verdict

- **Token-level visibility:** yes.
- **Per-agent governance:** yes, indirectly and realistically.
- **Native kagent “budget” field:** not documented as first-class.

---

## 12) Can I implement custom cost controls?

**Yes.** This is one of the stronger design points of the stack.

You can combine:

- API key authentication,
- rate limits,
- token budgets,
- per-user tracking,
- request defaults/overrides,
- model routing,
- external observability/alerting.

A very practical example is to use route defaults to clamp `max_tokens`, or override it when needed. Kgateway’s AI policy examples explicitly show overriding `max_tokens`.

### Recommended controls

1. **Hard request controls**  
   Clamp `max_tokens`, limit prompt size, restrict expensive models.

2. **Identity-based budgets**  
   Give each agent/team/tenant a separate virtual key or identity.

3. **Alerting and enforcement**  
   Use Prometheus/Grafana/Langfuse/LangSmith or your own pipeline for alerts and reporting.

4. **Fallback economics**  
   Route to cheaper models first, premium models only when needed.

### Practical verdict

**Yes — custom cost control is very achievable, especially when you treat the gateway as the policy enforcement point.**

---

## 13) Per-agent budgets or depth / token limits

### Per-agent budgets

Possible in practice, but usually implemented through **gateway identity and routing**, not directly on the `Agent` CR.

### Token limits

Possible through:

- provider/model config,
- gateway request defaults/overrides,
- application-side request shaping.

### Agent depth / loop limits

This is the part that is **least obviously first-class** in the docs.

For agent recursion depth, max tool hops, or max reasoning turns, the safest answer is:

- implement this in the **BYO runtime** (ADK, LangGraph, CrewAI, etc.),
- optionally surface it through policy/config,
- do not expect the model server or gateway to solve orchestration depth for you.

### Practical verdict

- **Per-agent budgets:** yes, with platform design.
- **Token limits:** yes.
- **Depth / loop limits:** yes, but mainly in the agent framework you bring.

---

## 14) Is vLLM suitable for agents with many back-and-forth tool calls, or is it better for single-shot inference?

### It is suitable for agentic workloads too

vLLM’s OpenAI-compatible server supports:

- chat/completions APIs,
- tool calling,
- reasoning outputs,
- structured outputs.

That means it can absolutely sit behind an agent loop where the agent repeatedly calls the model, invokes tools, and returns to the model.

### But it is important to separate concerns

vLLM is an **inference engine/server**, not the orchestration layer.

So the right mental model is:

- **kagent / ADK / LangGraph / CrewAI** = controls the loop
- **vLLM** = executes the model calls efficiently

### My assessment

- For **single-shot inference**, vLLM is strong.
- For **multi-step agent loops**, vLLM is still a good fit **if** you need strong serving performance or OpenAI-compatible self-hosting.
- For very small local setups with modest traffic, simpler local endpoints can be easier operationally.

### Practical verdict

**vLLM is not only for single-shot inference. It is suitable for agent loops too, but it solves the serving problem, not the planning/orchestration problem.**

---

## 15) llm-d’s scheduler — does it help when an agent makes 15 LLM calls?

### Yes, but indirectly

llm-d’s inference scheduler makes **optimized routing decisions** for inference requests and is specifically aimed at smarter scheduling for LLM serving. The docs emphasize:

- load-aware balancing,
- prefix-cache-aware balancing,
- SLA-aware routing,
- smart scheduling on top of Envoy/Gateway-based infrastructure.

The recommended inference-scheduling profile is described as reducing **tail latency** and increasing **throughput** for vLLM/SGLang deployments.

### What this means for a 15-call agent flow

If an agent makes 15 model calls, each of those is still an inference request. So yes, the scheduler can help by:

- routing each request to a better backend,
- improving cache locality,
- reducing queueing hotspots,
- lowering tail latency across repeated calls.

### What it does _not_ do

It does **not** reduce 15 agent steps to 1. It does **not** replace the agent runtime. It does **not** solve bad tool orchestration.

### My assessment

- **Small local deployment / single model instance:** benefit is limited.
- **Shared multi-GPU or multi-instance inference fleet:** benefit can be meaningful.
- **Prompt reuse / common prefixes / high concurrency:** benefit grows further.

### Practical verdict

**Yes, llm-d can help agent workloads with many model calls — especially at scale — but it optimizes inference routing, not the agent workflow itself.**

---

# Final recommendation for my setup

If I were explaining my target architecture to a customer or interviewer, I would position it like this:

## Recommended control split

### kagent

Use for:

- agent lifecycle,
- A2A exposure,
- MCP integration,
- Kubernetes-native deployment,
- agent composition.

### kmcp + FastMCP

Use for:

- fastest MCP server development path in Python,
- packaging tools cleanly,
- deploying MCP servers as Kubernetes resources.

### kgateway / agentgateway

Use for:

- provider abstraction,
- OpenAI/Anthropic/local failover,
- traffic splitting,
- timeouts/retries/circuit breakers,
- token governance,
- observability and FinOps.

### vLLM

Use when:

- I want local or self-hosted OpenAI-compatible inference,
- I need tool calling / structured outputs / reasoning support,
- I want better performance than simpler local runners.

### llm-d

Use when:

- inference becomes shared infrastructure,
- I need smarter routing across multiple serving replicas,
- cache locality and tail latency matter,
- I want to scale self-hosted inference beyond a basic single-endpoint setup.

## Short strategic summary

- **Yes**, the stack can support resilient agent execution.
- **Yes**, it can fail over between OpenAI, Claude, and local models.
- **Yes**, it can normalize many provider differences.
- **Yes**, it can support canary/blue-green patterns.
- **Yes**, it can support real FinOps controls.
- **But** the best results come from using **kagent for orchestration** and **kgateway for runtime policy and spend control**.

---

# Sources

## kagent / kmcp / MCP

- [kagent API reference](https://kagent.dev/docs/kagent/resources/api-ref)
- [kagent concepts: agents](https://www.kagent.dev/docs/kagent/concepts/agents)
- [Bring your own ADK agent to kagent](https://kagent.dev/docs/kagent/examples/a2a-byo)
- [kMCP quickstart](https://kagent.dev/docs/kmcp/quickstart)
- [Model Context Protocol: Build an MCP server](https://modelcontextprotocol.io/docs/develop/build-server)
- [FastMCP Python repository](https://github.com/fastmcp-me/fastmcp-python)

## kgateway / agentgateway

- [Model failover](https://kgateway.dev/docs/agentgateway/latest/llm/failover/)
- [OpenAI-compatible providers](https://kgateway.dev/docs/agentgateway/latest/llm/providers/openai-compatible)
- [Anthropic provider](https://kgateway.dev/docs/agentgateway/latest/llm/providers/anthropic/)
- [LLM consumption overview](https://kgateway.dev/docs/agentgateway/main/llm/about)
- [API keys / virtual-key style controls](https://kgateway.dev/docs/agentgateway/latest/llm/api-keys/)
- [Metrics and logs](https://kgateway.dev/docs/agentgateway/latest/llm/observability)
- [Timeouts](https://kgateway.dev/docs/envoy/main/resiliency/timeouts/about/)
- [Retries](https://kgateway.dev/docs/envoy/main/resiliency/retry/retry/)
- [Per-try timeout](https://kgateway.dev/docs/envoy/main/resiliency/retry/per-try-timeout/)
- [Envoy API reference / circuit breakers and policy fields](https://kgateway.dev/docs/envoy/latest/reference/api/)
- [Canary deployments with kgateway and Argo Rollouts](https://kgateway.dev/blog/canary-deployments-argo-rollouts/)
- [HTTPRoute traffic splitting overview](https://kgateway.dev/blog/exploring-gateway-api-httproute/)
- [kagent argo-rollouts-conversion-agent](https://kagent.dev/agents/argo-rollouts-conversion-agent)

## vLLM

- [OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/)
- [Tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/)
- [Reasoning outputs](https://docs.vllm.ai/en/latest/features/reasoning_outputs/)
- [Structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/)

## llm-d

- [llm-d architecture](https://llm-d.ai/docs/architecture)
- [Inference Scheduler](https://llm-d.ai/docs/architecture/Components/inference-scheduler)
- [Intelligent Inference Scheduling](https://llm-d.ai/docs/guide/Installation/inference-scheduling)
