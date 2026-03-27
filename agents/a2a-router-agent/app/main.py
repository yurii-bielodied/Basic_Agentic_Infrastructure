import os
import re
from typing import Any, Optional
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Kagent A2A Router Agent", version="0.2.0")

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "http://a2a-router-agent.kagent.svc.cluster.local:8080",
).rstrip("/")

REMOTE_AGENT_BASE = os.getenv(
    "KAGENT_REMOTE_AGENT_BASE",
    "http://kagent-controller.kagent.svc.cluster.local:8083/api/a2a/kagent/k8s-agent",
).rstrip("/")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
DEFAULT_NAMESPACE = os.getenv("DEFAULT_NAMESPACE", "default")

RESOURCE_ALIASES = {
    "pod": "pods",
    "pods": "pods",
    "po": "pods",
    "service": "services",
    "services": "services",
    "svc": "services",
    "deployment": "deployments",
    "deployments": "deployments",
    "deploy": "deployments",
    "statefulset": "statefulsets",
    "statefulsets": "statefulsets",
    "sts": "statefulsets",
    "job": "jobs",
    "jobs": "jobs",
    "cronjob": "cronjobs",
    "cronjobs": "cronjobs",
    "cj": "cronjobs",
}

SUPPORTED_EXAMPLES = [
    "Show pods in namespace kagent",
    "Get services in namespace istio-system",
    "List deployments in namespace phoenix",
    "Show cronjobs in namespace default",
]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/agent-card.json")
async def get_agent_card_latest() -> dict[str, Any]:
    return build_agent_card()


@app.get("/.well-known/agent.json")
async def get_agent_card_legacy() -> dict[str, Any]:
    return build_agent_card()


@app.post("/")
async def handle_jsonrpc(request: Request) -> JSONResponse:
    body = await request.json()
    req_id = body.get("id", uuid4().hex)
    method = body.get("method")

    if method not in {"message/send", "SendMessage"}:
        return JSONResponse(
            rpc_error(req_id, -32601, f"Unsupported method: {method}"),
            status_code=400,
        )

    params = body.get("params", {})
    message = params.get("message", {})
    return await process_message(req_id=req_id, message=message, rest_mode=False)


@app.post("/message:send")
async def handle_rest_send(request: Request) -> JSONResponse:
    body = await request.json()
    message = body.get("message", {})
    return await process_message(req_id=uuid4().hex, message=message, rest_mode=True)


async def process_message(
    req_id: str,
    message: dict[str, Any],
    rest_mode: bool = False,
) -> JSONResponse:
    user_text = extract_text_from_message(message)
    context_id = message.get("contextId") or uuid4().hex

    if not user_text.strip():
        payload = task_failure_payload(
            context_id=context_id,
            error_text="Empty input. Send a text request such as 'Show pods in namespace kagent'.",
        )
        return JSONResponse(payload if rest_mode else rpc_result(req_id, payload), status_code=400)

    try:
        normalized_task = normalize_user_request(user_text)
    except ValueError as exc:
        payload = task_failure_payload(
            context_id=context_id,
            error_text=str(exc),
        )
        return JSONResponse(payload if rest_mode else rpc_result(req_id, payload), status_code=400)

    try:
        remote_card = await fetch_remote_agent_card()
        remote_result = await send_message_to_remote_agent(
            remote_url=remote_card.get("url", REMOTE_AGENT_BASE),
            task_text=normalized_task,
            context_id=context_id,
        )
    except Exception as exc:
        payload = task_failure_payload(
            context_id=context_id,
            error_text=f"Remote kagent agent call failed: {exc}",
        )
        return JSONResponse(payload if rest_mode else rpc_result(req_id, payload), status_code=502)

    remote_task = extract_task(remote_result)
    remote_text = extract_primary_text(remote_task)

    summary = (
        f"Router agent normalized the request to: {normalized_task}\n\n"
        f"Remote agent endpoint: {remote_card.get('url', REMOTE_AGENT_BASE)}\n\n"
        f"Remote agent reply:\n{remote_text or '[no text artifact returned]'}"
    )

    task = build_completed_task(
        context_id=context_id,
        summary_text=summary,
        metadata={
            "normalizedTask": normalized_task,
            "remoteAgentName": remote_card.get("name"),
            "remoteTaskId": remote_task.get("id") if isinstance(remote_task, dict) else None,
        },
    )

    payload = {"task": task}
    return JSONResponse(payload if rest_mode else rpc_result(req_id, payload))


async def fetch_remote_agent_card() -> dict[str, Any]:
    base = REMOTE_AGENT_BASE.rstrip("/")
    candidates = [
        f"{base}/.well-known/agent.json",
        f"{base}/.well-known/agent-card.json",
    ]

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        last_error: Optional[Exception] = None

        for url in candidates:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    return data
                raise RuntimeError(
                    f"Remote agent card from {url} is not a JSON object")
            except Exception as exc:
                last_error = exc

        if last_error:
            raise last_error
        raise RuntimeError("No remote agent card endpoint responded")


async def send_message_to_remote_agent(
    remote_url: str,
    task_text: str,
    context_id: str,
) -> dict[str, Any]:
    remote_base = remote_url.rstrip("/")

    rpc_payload = {
        "jsonrpc": "2.0",
        "id": uuid4().hex,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": uuid4().hex,
                "contextId": context_id,
                "parts": [
                    {
                        "kind": "text",
                        "text": task_text,
                    }
                ],
            }
        },
    }

    rest_payload = {
        "message": {
            "role": "user",
            "messageId": uuid4().hex,
            "contextId": context_id,
            "parts": [
                {
                    "kind": "text",
                    "text": task_text,
                }
            ],
        }
    }

    candidates = [
        ("jsonrpc", f"{remote_base}/", rpc_payload),
        ("jsonrpc", remote_base, rpc_payload),
        ("rest", f"{remote_base}/message:send", rest_payload),
    ]

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        last_error: Optional[Exception] = None

        for mode, url, payload in candidates:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()

                if mode == "rest":
                    return {"task": result.get("task", result)} if isinstance(result, dict) else {"task": result}
                return result
            except Exception as exc:
                last_error = exc

        if last_error:
            raise last_error
        raise RuntimeError("All remote invocation attempts failed")


def normalize_user_request(user_text: str) -> str:
    lowered = user_text.lower()

    namespace_match = re.search(
        r"\b(?:namespace|ns)\s+([a-z0-9-]+)\b", lowered)
    namespace = namespace_match.group(
        1) if namespace_match else DEFAULT_NAMESPACE

    resource = None
    for alias, normalized in RESOURCE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            resource = normalized
            break

    if resource is None:
        supported = ", ".join(sorted(set(RESOURCE_ALIASES.values())))
        raise ValueError(
            "Unsupported request. This demo router supports only resource listing for: "
            f"{supported}. Example: 'Show pods in namespace kagent'."
        )

    return f"Get the {resource} in the {namespace} namespace"


def extract_text_from_message(message: dict[str, Any]) -> str:
    texts: list[str] = []

    for part in message.get("parts", []):
        if isinstance(part, dict):
            if isinstance(part.get("text"), str):
                texts.append(part["text"])
            elif isinstance(part.get("root"), dict) and isinstance(part["root"].get("text"), str):
                texts.append(part["root"]["text"])

    return "\n".join(texts).strip()


def extract_task(remote_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(remote_result, dict):
        return {"artifacts": [{"parts": [{"kind": "text", "text": str(remote_result)}]}]}

    if "result" in remote_result and isinstance(remote_result["result"], dict):
        result = remote_result["result"]
        if "task" in result and isinstance(result["task"], dict):
            return result["task"]
        if "artifact" in result:
            return {"artifacts": [result["artifact"]]}

    if "task" in remote_result and isinstance(remote_result["task"], dict):
        return remote_result["task"]

    return remote_result


def extract_primary_text(task: dict[str, Any]) -> Optional[str]:
    if not isinstance(task, dict):
        return None

    status_msg = task.get("status", {}).get("message")
    if isinstance(status_msg, dict):
        text = extract_text_from_message(status_msg)
        if text:
            return text

    for artifact in task.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        for part in artifact.get("parts", []):
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                return part["text"]

    return None


def build_agent_card() -> dict[str, Any]:
    return {
        "name": "kagent_a2a_router",
        "description": "A simple A2A router that normalizes Kubernetes listing requests and delegates them to a remote kagent Kubernetes A2A agent.",
        "url": f"{PUBLIC_BASE_URL}/",
        "version": "0.2.0",
        "protocolVersion": "0.2.6",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": "route-k8s-resource-list",
                "name": "Route Kubernetes resource list tasks",
                "description": "Converts a simple user request into a normalized Kubernetes listing task and delegates it to a remote kagent A2A agent.",
                "tags": ["k8s", "a2a", "router", "kagent"],
                "examples": SUPPORTED_EXAMPLES,
                "inputModes": ["text"],
                "outputModes": ["text"],
            }
        ],
    }


def build_completed_task(
    context_id: str,
    summary_text: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "id": uuid4().hex,
        "contextId": context_id,
        "status": {
            "state": "completed",
            "message": {
                "role": "agent",
                "parts": [{"kind": "text", "text": summary_text}],
                "messageId": uuid4().hex,
            },
        },
        "artifacts": [
            {
                "artifactId": uuid4().hex,
                "name": "delegation-result.txt",
                "parts": [{"kind": "text", "text": summary_text}],
            }
        ],
        "metadata": metadata or {},
    }


def task_failure_payload(context_id: Optional[str], error_text: str) -> dict[str, Any]:
    task = {
        "id": uuid4().hex,
        "contextId": context_id or uuid4().hex,
        "status": {
            "state": "failed",
            "message": {
                "role": "agent",
                "parts": [{"kind": "text", "text": error_text}],
                "messageId": uuid4().hex,
            },
        },
        "artifacts": [
            {
                "artifactId": uuid4().hex,
                "name": "error.txt",
                "parts": [{"kind": "text", "text": error_text}],
            }
        ],
    }
    return {"task": task}


def rpc_result(req_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }


def rpc_error(req_id: str, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }
