# Kagent on Kind with Terraform, AgentGateway, and Ollama

![Terraform](https://img.shields.io/badge/Terraform-IaC-623CE4?logo=terraform&logoColor=white)
![Flux](https://img.shields.io/badge/Flux-GitOps-CE3262?logo=fluxcd&logoColor=white)
![Helm](https://img.shields.io/badge/Helm-Kubernetes%20Packages-0F1689?logo=helm&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-Kind%20Cluster-326CE5?logo=kubernetes&logoColor=white)
![Kind](https://img.shields.io/badge/Kind-Local%20K8s-009688)
![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-111111)
![Kagent](https://img.shields.io/badge/Kagent-AI%20Agent%20UI-FF6B35)
![AgentGateway](https://img.shields.io/badge/AgentGateway-Gateway%20Layer-2E8B57)

A local Kubernetes-based AI agent playground deployed with **Terraform** on a **Kind** cluster. The stack installs **Gateway API**, **AgentGateway**, **Kagent**, and connects Kagent to a locally running **Ollama** model (`qwen3:14b`).

This setup is useful for local development, demos, experimentation, and validating the deployment flow before moving to a larger Kubernetes environment.

---

## Overview

This project provisions and configures:

- a local **Kind** Kubernetes cluster
- **Gateway API** experimental CRDs
- **Flux CD** for infrastructure as code GitOps
- **AgentGateway** CRDs and controller (managed via Flux)
- local **Ollama** model pull for `qwen3:14b`
- **Kagent** CRDs and application (managed via Flux)
- Kagent configured to use **Ollama** as the default provider

The infrastructure is managed using **Flux** GitOps approach:

- Terraform handles Kind cluster provisioning, Gateway API, Ollama, and Flux setup
- Flux manifests in `infra/` directory manage AgentGateway and Kagent deployments

### Access Kagent UI

Kagent UI can be accessed locally through the AgentGateway proxy:

```bash
kubectl port-forward -n agentgateway-system svc/agentgateway-proxy 8080:8080
```

Then open in your browser:

```text
http://localhost:8080
```

**Note:** The UI is protected with basic authentication.

- Username: `kagent-ui`
- Password: `KagentUI2026!`

### Access Flux Status UI

To view Flux automation status and reconciliation details:

```bash
kubectl port-forward -n flux-system svc/flux-operator 9080:9080
```

Then open in your browser:

```text
http://localhost:9080
```

---

## Architecture

The deployment flow is:

1. Terraform creates the local Kind cluster.
2. Terraform installs Flux CD and flux-operator.
3. Gateway API CRDs are installed via Terraform.
4. Flux reconciles manifests from `infra/` directory which includes:
   - AgentGateway CRDs and AgentGateway installation
   - Kagent CRDs and Kagent installation
5. Ollama pulls the `qwen3:14b` model on the host machine via Terraform provisioner.
6. Kagent connects to Ollama via `http://host.docker.internal:11434`.
7. The Kagent UI is exposed locally through AgentGateway proxy with basic authentication.

### Block Diagram

```mermaid
flowchart TD
    U[User Browser] -->|http://localhost:8080| PF1[kubectl port-forward]
    PF1 --> AGW[agentgateway-proxy]
    AGW --> AUTH[Basic Auth Policy]
    AUTH --> KAGENT_SVC[kagent-ui Service]
    KAGENT_SVC --> UI[Kagent UI Pod]
    UI --> KAGENT[Kagent Backend]
    KAGENT -->|default provider: ollama| OLLAMA[Ollama API\nhost.docker.internal:11434]
    OLLAMA --> MODEL[qwen3:14b Model]

    U2[Developer] -->|http://localhost:9080| PF2[kubectl port-forward]
    PF2 --> FLUX[flux-operator UI]
    FLUX --> FLUX_STATUS[Flux Status & Automation]

    TF[Terraform] --> KIND[Kind Cluster]
    TF --> GWAPI[Gateway API CRDs]
    TF --> FLUX_DEPLOY[Flux CD Setup]
    TF --> OLPULL[ollama pull qwen3:14b]

    KIND --> FLUX_DEPLOY
    FLUX_DEPLOY --> GitOps[GitOps Reconciliation]
    GitOps --> AGCRD[AgentGateway CRDs]
    GitOps --> AGW
    GitOps --> KCRD[Kagent CRDs]
    GitOps --> KAGENT_DEPLOY[Kagent Helm Release]
    KIND --> AGW
    KIND --> KAGENT_DEPLOY
    KIND --> KAGENT_SVC
```

---

## Requirements

### Software

Make sure the following tools are installed and available in your `PATH`:

- **Terraform** `>= 1.14`
- **kubectl** compatible with your Kubernetes version
- **Helm** `>= 3.1`
- **Docker** (Docker Engine or Docker Desktop)
- **Ollama**

### System Requirements

Recommended minimum for a smoother experience with `qwen3:14b`:

- **CPU:** modern 8-core CPU or better
- **RAM:** at least **16 GB**, preferably **32 GB**
- **Disk:** at least **20 GB** free space
- **GPU:** a **dedicated GPU** is strongly recommended for better inference speed

### GPU Notes

`qwen3:14b` can be very heavy for a small laptop.

Recommended:

- NVIDIA GPU with sufficient VRAM for local inference
- or a powerful discrete/external GPU setup if your workstation supports it

Without a GPU, the stack may still work in CPU mode, but responses can be slow and host resource usage can be high.

### Networking Notes

This setup expects Kagent to reach Ollama at:

```text
http://host.docker.internal:11434
```

This usually works well with Docker Desktop environments. On some Linux setups, `host.docker.internal` may require additional configuration.

---

## Project Components

The provided Terraform configuration includes:

- `module "kind_cluster"` – creates the local Kind cluster
- `null_resource.install_gatewayapi` – installs Gateway API CRDs from the official release manifest
- `module "flux"` – installs Flux CD and sets up GitOps from this repository
- `null_resource.manage_ollama_model` – pulls the `qwen3:14b` model locally with Ollama

### Flux-Managed Components

The `infra/` directory contains Flux manifests that define:

#### `infra/crds/`

- **agentgateway-crds.yaml** – AgentGateway CRD definitions
- **kagent-crds.yaml** – Kagent CRD definitions

#### `infra/manifests/`

- **agentgateway.yaml** – AgentGateway installation and configuration:
  - `AgentgatewayParameters` – logging configuration
  - `Gateway` (agentgateway-proxy) – HTTP listener on port 8080
  - `AgentgatewayPolicy` – basic authentication for Kagent UI

- **kagent.yaml** – Kagent installation and configuration:
  - Kagent CRD installation
  - Kagent UI and controller deployment
  - HTTPRoute – routes requests to Kagent services
  - Provider configuration for Ollama:
    ```yaml
    providers:
      default: ollama
      ollama:
        provider: "Ollama"
        model: "qwen3:14b"
        config:
          host: "http://host.docker.internal:11434"
    ```

The Flux system automatically reconciles these manifests from the Git repository, providing continuous deployment and declarative infrastructure management.

---

## Prerequisites

Before deployment:

1. Start Docker.
2. Make sure Kind can create clusters locally.
3. Install and start Ollama.
4. Verify Ollama is reachable:

```bash
ollama list
curl http://localhost:11434/api/tags
```

5. Ensure Terraform can access your Kubernetes and Helm providers.

---

## Initialization

Initialize Terraform in the project directory:

```bash
terraform init
```

Validate the configuration:

```bash
terraform validate
```

Review the execution plan:

```bash
terraform plan
```

---

## Deployment

Apply the infrastructure:

```bash
terraform apply
```

Terraform will:

- create the Kind cluster
- install Gateway API and Flux CD
- pull the Ollama model `qwen3:14b`
- Flux will then automatically reconcile and install:
  - AgentGateway
  - Kagent

The entire setup is now managed through GitOps with Flux. Check [Verify the Deployment](#verify-the-deployment) section to confirm all components are running.

---

## Verify the Deployment

Check cluster nodes:

```bash
kubectl get nodes
```

Check namespaces:

```bash
kubectl get ns
```

Check Flux system and reconciliation status:

```bash
kubectl get ns flux-system
kubectl get pods -n flux-system
kubectl get helmrelease -A  # View all Helm releases managed by Flux
kubectl get ocirepo -n flux-system  # View OCI repositories
```

Check Kagent resources:

```bash
kubectl get pods -n kagent
kubectl get svc -n kagent
kubectl get helmrelease -n kagent
```

Check AgentGateway resources:

```bash
kubectl get pods -n agentgateway-system
kubectl get svc -n agentgateway-system
kubectl get gateway -n agentgateway-system
kubectl get httproad -n kagent
```

Verify Flux reconciliation with events:

```bash
kubectl describe helmrelease agentgateway -n agentgateway-system
kubectl describe helmrelease kagent -n kagent
kubectl logs -n flux-system deployment/flux-operator  # Check Flux operator logs
```

---

## Example Workflow

A typical local workflow:

```bash
# Initialize and deploy
terraform init
terraform plan
terraform apply -auto-approve

# Verify Flux is reconciling
kubectl get pods -n flux-system
kubectl get helmrelease -A

# Access Kagent UI (in one terminal)
kubectl port-forward -n agentgateway-system svc/agentgateway-proxy 8080:8080
# Then open http://localhost:8080

# Monitor Flux Status UI (optional, in another terminal)
kubectl port-forward -n flux-system svc/flux-operator 9080:9080
# Then open http://localhost:9080
```

Credentials for Kagent UI:

- **Username:** `kagent-ui`
- **Password:** `KagentUI2026!`

---

## Troubleshooting

### 1. Flux reconciliation failed

Check Flux operator logs and HelmRelease status:

```bash
kubectl logs -n flux-system deployment/flux-operator -f
kubectl describe helmrelease agentgateway -n agentgateway-system
kubectl describe helmrelease kagent -n kagent
```

If manifests are not being applied, check GitRepository:

```bash
kubectl describe gitrepository infra -n flux-system
```

### 2. Ollama is not reachable from Kagent

Check that Ollama is running on the host:

```bash
curl http://localhost:11434/api/tags
```

If Kagent cannot reach `host.docker.internal`, verify your Docker/Kind networking setup.

### 3. Model pull takes a long time

`qwen3:14b` is a large model. Initial download can take significant time depending on bandwidth and disk performance.

Check downloaded models:

```bash
ollama list
```

### 4. Pods are not starting

Inspect pods and events:

```bash
kubectl get pods -A
kubectl describe pod -n kagent <pod-name>
kubectl logs -n kagent <pod-name>
kubectl describe pod -n agentgateway-system <pod-name>
kubectl logs -n agentgateway-system <pod-name>
```

### 5. Port-forward fails

Verify the services exist:

```bash
kubectl get svc -n agentgateway-system      # Check agentgateway-proxy
kubectl get svc -n kagent                   # Check kagent-ui
kubectl get svc -n flux-system              # Check flux-operator
```

Then retry:

```bash
kubectl port-forward -n agentgateway-system svc/agentgateway-proxy 8080:8080
```

### 6. AgentGateway Policy not being applied

Check if the policy is targeting the correct Gateway:

```bash
kubectl get agentgatewaypolicy -n agentgateway-system
kubectl describe agentgatewaypolicy kagent-ui-basic-auth -n agentgateway-system
```

Verify the Gateway name matches the policy targetRef:

```bash
kubectl get gateway -n agentgateway-system
```

---

## Cleanup

To destroy the environment:

```bash
terraform destroy
```

This will:

- Destroy the Kind cluster (which removes all Kubernetes resources including Flux-managed applications)
- Trigger the Ollama stop provisioner

**Note:** Flux manifests are automatically cleaned up when the Kind cluster is destroyed, but the Git repository continues to contain the infrastructure definitions.

---

## Notes

- This setup is intended primarily for **local development and testing**.
- Running large local LLMs can consume substantial CPU, memory, disk, and GPU resources.
- Infrastructure is managed through **Flux CD** for declarative GitOps workflow.
- All application deployments (AgentGateway, Kagent) are defined in the `infra/` directory and automatically reconciled by Flux.
- For production-style environments, consider replacing the local Kind + host Ollama pattern with a more robust Kubernetes-based inference backend.

---

## Repository Goal

This repository demonstrates how to combine:

- **Terraform** for repeatable infrastructure provisioning
- **Flux CD** for GitOps continuous deployment
- **Kind** for local Kubernetes
- **Helm** for application installation (via Flux)
- **Ollama** for local LLM serving
- **Kagent** for agent interaction UI
- **AgentGateway** for gateway-layer capabilities

into one reproducible local AI platform with declarative infrastructure management.
