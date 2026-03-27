# A2A router agent for kagent

This project implements a minimal custom A2A router agent for a coursework or certificate-style task.

The router agent:

- exposes its own Agent Card by well-known URI;
- accepts simple A2A requests;
- normalizes a small set of Kubernetes read-only listing requests;
- delegates the normalized request to an existing `k8s-agent` running in kagent;
- returns the delegated result as its own completed task.

## Architecture

```text
User / client
    |
    v
Custom router agent
/.well-known/agent-card.json
/.well-known/agent.json
POST /           (JSON-RPC)
POST /message:send
    |
    | normalize request
    v
kagent controller A2A endpoint
/api/a2a/kagent/k8s-agent/
    |
    v
k8s-agent
    |
    v
Kubernetes tools in kagent
```
