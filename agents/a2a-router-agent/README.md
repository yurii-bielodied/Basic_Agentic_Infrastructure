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

## Build and Deploy

For detailed build and deployment instructions, see the main project README:

- **Building the image:** see [`README.md` - Building and Deploying the A2A Router Agent](../../README.md#building-and-deploying-the-a2a-router-agent)
- **Deploying via Flux:** see [`README.md` - Custom Agent: A2A Router Agent](../../README.md#custom-agent-a2a-router-agent)

### Quick Build

1. Update the image reference in `infra/manifests/a2a-router-agent/a2a-router-agent.yaml`
2. Trigger the GitHub Actions workflow (or manually build with Docker)
3. Flux automatically reconciles the new image

### Accessing the Agent Card

The running agent exposes its metadata via the Agent Card URI:

```bash
kubectl port-forward -n kagent svc/kagent-controller 8083:8083
```

Then access:

```text
http://127.0.0.1:8083/api/a2a/kagent/a2a-router-agent/.well-known/agent.json
```
