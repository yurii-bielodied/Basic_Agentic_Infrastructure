import json
import logging
import os
import re
from typing import Any, Optional
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Kagent A2A Router Agent", version="0.6.4")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("a2a-router-agent")

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "http://a2a-router-agent.kagent.svc.cluster.local:8080",
).rstrip("/")

REMOTE_AGENT_BASE = os.getenv(
    "KAGENT_REMOTE_AGENT_BASE",
    "http://kagent-controller.kagent.svc.cluster.local:8083/api/a2a/kagent/k8s-agent/",
).rstrip("/")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SECONDS", "180"))
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
    "namespace": "namespaces",
    "namespaces": "namespaces",
    "ns": "namespaces",
}

SUPPORTED_EXAMPLES = [
    "Get pods",
    "Get pods kagent",
    "Get pods in namespace kagent",
    "Get pods from ns kagent",
    "Get services in namespace istio-system",
    "List deployments in phoenix",
    "List namespaces",
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
async def handle_jsonrpc(request: Request):
    body = await request.json()
    req_id = body.get("id", uuid4().hex)
    method = body.get("method")
    params = body.get("params", {})
    message = params.get("message", {})

    logger.info("Received JSON-RPC request method=%s req_id=%s", method, req_id)

    if method in {"message/send", "SendMessage"}:
        return await process_message(req_id=req_id, message=message, rest_mode=False)

    if method in {"message/stream", "SendStreamingMessage"}:
        return await process_message_stream(req_id=req_id, message=message)

    logger.warning(
        "Unsupported JSON-RPC method=%s req_id=%s body=%s", method, req_id, body
    )
    return JSONResponse(
        rpc_error(req_id, -32601, f"Unsupported method: {method}"),
        status_code=400,
    )


@app.post("/message:send")
async def handle_rest_send(request: Request) -> JSONResponse:
    body = await request.json()
    message = body.get("message", {})
    logger.info("Received REST send request")
    return await process_message(req_id=uuid4().hex, message=message, rest_mode=True)


@app.post("/message:stream")
async def handle_rest_stream(request: Request) -> StreamingResponse:
    body = await request.json()
    message = body.get("message", {})
    logger.info("Received REST stream request")
    return await process_message_stream(req_id=uuid4().hex, message=message)


async def process_message(
    req_id: str,
    message: dict[str, Any],
    rest_mode: bool = False,
) -> JSONResponse:
    router_context_id = message.get("contextId") or uuid4().hex
    user_text = extract_text_from_message(message)

    logger.info(
        "Processing message req_id=%s router_context_id=%s user_text=%r",
        req_id,
        router_context_id,
        user_text,
    )

    if not user_text.strip():
        payload = task_failure_payload(
            context_id=router_context_id,
            error_text="Empty input. Example: 'Get pods' or 'List namespaces'.",
        )
        return JSONResponse(
            payload if rest_mode else rpc_result(req_id, payload),
            status_code=400,
        )

    try:
        normalized_task = normalize_user_request(user_text)
        logger.info("Normalized request: %s", normalized_task)
    except ValueError as exc:
        payload = task_failure_payload(
            context_id=router_context_id,
            error_text=str(exc),
        )
        return JSONResponse(
            payload if rest_mode else rpc_result(req_id, payload),
            status_code=400,
        )

    remote_context_id = f"remote-{uuid4().hex}"
    logger.info(
        "Using separate remote_context_id=%s for router_context_id=%s",
        remote_context_id,
        router_context_id,
    )

    try:
        remote_result = await send_message_to_remote_agent(
            remote_url=REMOTE_AGENT_BASE,
            task_text=normalized_task,
            remote_context_id=remote_context_id,
        )
    except Exception as exc:
        logger.exception("Remote kagent agent call failed")
        payload = task_failure_payload(
            context_id=router_context_id,
            error_text=f"Remote kagent agent call failed: {exc}",
        )
        return JSONResponse(
            payload if rest_mode else rpc_result(req_id, payload),
            status_code=502,
        )

    remote_payload = extract_remote_payload(remote_result)
    remote_text = extract_primary_text(remote_payload)

    summary = build_summary(
        normalized_task=normalized_task,
        remote_endpoint=REMOTE_AGENT_BASE.rstrip("/") + "/",
        remote_text=remote_text,
        remote_result=remote_result,
        router_context_id=router_context_id,
        remote_context_id=remote_context_id,
    )

    task = build_completed_task(
        context_id=router_context_id,
        summary_text=summary,
        metadata={
            "normalizedTask": normalized_task,
            "remoteTaskId": remote_payload.get("id") if isinstance(remote_payload, dict) else None,
            "remoteContextId": remote_context_id,
        },
    )

    payload = {"task": task}
    return JSONResponse(payload if rest_mode else rpc_result(req_id, payload))


async def process_message_stream(
    req_id: str,
    message: dict[str, Any],
) -> StreamingResponse:
    router_context_id = message.get("contextId") or uuid4().hex
    task_id = uuid4().hex
    user_text = extract_text_from_message(message)

    logger.info(
        "Processing stream req_id=%s router_context_id=%s user_text=%r",
        req_id,
        router_context_id,
        user_text,
    )

    async def event_generator():
        yield sse_data(
            stream_result(
                req_id,
                build_status_update_event(
                    task_id=task_id,
                    context_id=router_context_id,
                    state="working",
                    final=False,
                    text="Router agent is processing the request.",
                ),
            )
        )

        if not user_text.strip():
            yield sse_data(
                stream_result(
                    req_id,
                    build_status_update_event(
                        task_id=task_id,
                        context_id=router_context_id,
                        state="failed",
                        final=True,
                        text="Empty input. Example: 'Get pods' or 'List namespaces'.",
                    ),
                )
            )
            return

        try:
            normalized_task = normalize_user_request(user_text)
            logger.info("Normalized streaming request: %s", normalized_task)
        except ValueError as exc:
            yield sse_data(
                stream_result(
                    req_id,
                    build_status_update_event(
                        task_id=task_id,
                        context_id=router_context_id,
                        state="failed",
                        final=True,
                        text=str(exc),
                    ),
                )
            )
            return

        yield sse_data(
            stream_result(
                req_id,
                build_status_update_event(
                    task_id=task_id,
                    context_id=router_context_id,
                    state="working",
                    final=False,
                    text=f"Delegating normalized task: {normalized_task}",
                ),
            )
        )

        remote_context_id = f"remote-{uuid4().hex}"
        logger.info(
            "Streaming mode: router_context_id=%s remote_context_id=%s",
            router_context_id,
            remote_context_id,
        )

        try:
            remote_result = await send_message_to_remote_agent(
                remote_url=REMOTE_AGENT_BASE,
                task_text=normalized_task,
                remote_context_id=remote_context_id,
            )
            remote_payload = extract_remote_payload(remote_result)
            remote_text = extract_primary_text(remote_payload)

            summary = build_summary(
                normalized_task=normalized_task,
                remote_endpoint=REMOTE_AGENT_BASE.rstrip("/") + "/",
                remote_text=remote_text,
                remote_result=remote_result,
                router_context_id=router_context_id,
                remote_context_id=remote_context_id,
            )

            yield sse_data(
                stream_result(
                    req_id,
                    build_status_update_event(
                        task_id=task_id,
                        context_id=router_context_id,
                        state="completed",
                        final=True,
                        text=summary,
                        metadata={
                            "normalizedTask": normalized_task,
                            "remoteTaskId": remote_payload.get("id") if isinstance(remote_payload, dict) else None,
                            "remoteContextId": remote_context_id,
                        },
                    ),
                )
            )
            return

        except Exception as exc:
            logger.exception("Remote kagent agent streaming call failed")
            yield sse_data(
                stream_result(
                    req_id,
                    build_status_update_event(
                        task_id=task_id,
                        context_id=router_context_id,
                        state="failed",
                        final=True,
                        text=f"Remote kagent agent call failed: {exc}",
                    ),
                )
            )
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def send_message_to_remote_agent(
    remote_url: str,
    task_text: str,
    remote_context_id: str,
) -> dict[str, Any]:
    remote_base = remote_url.rstrip("/") + "/"

    rpc_payload = {
        "jsonrpc": "2.0",
        "id": uuid4().hex,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": uuid4().hex,
                "contextId": remote_context_id,
                "parts": [
                    {
                        "kind": "text",
                        "text": task_text,
                    }
                ],
            }
        },
    }

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        logger.info(
            "Sending remote message url=%s remote_context_id=%s task_text=%r",
            remote_base,
            remote_context_id,
            task_text,
        )
        response = await client.post(remote_base, json=rpc_payload)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        logger.info(
            "Remote response status=%s url=%s content_type=%s",
            response.status_code,
            str(response.url),
            content_type,
        )

        result = response.json()

        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(
                f"Remote agent returned JSON-RPC error: {result['error']}")

        return result


def normalize_user_request(user_text: str) -> str:
    lowered = user_text.lower().strip()
    cleaned = re.sub(r"[,:;!?()\[\]{}]+", " ", lowered)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    resource = detect_resource(cleaned)
    if resource is None:
        supported = ", ".join(sorted(set(RESOURCE_ALIASES.values())))
        raise ValueError(
            "Unsupported request. This demo router supports only resource listing for: "
            f"{supported}. Examples: 'Get pods', 'Get pods kagent', 'Get services in namespace istio-system'."
        )

    if resource == "namespaces":
        return "Get the namespaces"

    namespace = detect_namespace(cleaned) or DEFAULT_NAMESPACE
    return f"Get the {resource} in the {namespace} namespace"


def detect_resource(text: str) -> Optional[str]:
    patterns = sorted(RESOURCE_ALIASES.items(),
                      key=lambda x: len(x[0]), reverse=True)
    for alias, normalized in patterns:
        if re.search(rf"(?<![a-z0-9-]){re.escape(alias)}(?![a-z0-9-])", text):
            return normalized
    return None


def detect_namespace(text: str) -> Optional[str]:
    patterns = [
        r"\bfrom\s+(?:namespace|ns)\s+([a-z0-9-]+)\b",
        r"\bin\s+(?:namespace|ns)\s+([a-z0-9-]+)\b",
        r"\b(?:namespace|ns)\s+([a-z0-9-]+)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    tokens = text.split()
    if len(tokens) >= 3:
        last_token = tokens[-1]
        reserved = {
            "get", "list", "show",
            "pod", "pods", "po",
            "service", "services", "svc",
            "deployment", "deployments", "deploy",
            "statefulset", "statefulsets", "sts",
            "job", "jobs",
            "cronjob", "cronjobs", "cj",
            "namespace", "namespaces", "ns",
            "in", "from", "all",
        }
        if re.fullmatch(r"[a-z0-9-]+", last_token) and last_token not in reserved:
            return last_token

    return None


def extract_text_from_message(message: dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""

    texts: list[str] = []

    for part in message.get("parts", []):
        text = part_to_text(part)
        if text:
            texts.append(text)

    return "\n".join(texts).strip()


def part_to_text(part: Any) -> Optional[str]:
    if not isinstance(part, dict):
        return None

    text = part.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    root = part.get("root")
    if isinstance(root, dict):
        root_text = root.get("text")
        if isinstance(root_text, str) and root_text.strip():
            return root_text.strip()

    data = part.get("data")
    if data is not None:
        if isinstance(data, str) and data.strip():
            return data.strip()
        try:
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            return str(data)

    return None


def collect_texts_from_parts(parts: Any) -> list[str]:
    texts: list[str] = []
    if not isinstance(parts, list):
        return texts

    for part in parts:
        text = part_to_text(part)
        if text:
            texts.append(text)

    return texts


def extract_remote_payload(remote_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(remote_result, dict):
        return {"artifacts": [{"parts": [{"kind": "text", "text": str(remote_result)}]}]}

    # JSON-RPC response wrapper
    if isinstance(remote_result.get("result"), dict):
        result = remote_result["result"]

        # REST-like wrappers nested under result
        if isinstance(result.get("task"), dict):
            return result["task"]
        if isinstance(result.get("message"), dict):
            return result["message"]
        if isinstance(result.get("artifact"), dict):
            return {"artifacts": [result["artifact"]]}

        # Direct Task / Message / artifact-update-like payload in result
        if any(
            key in result
            for key in ("status", "artifacts", "parts", "history", "artifact", "kind", "id", "contextId")
        ):
            return result

    # REST response wrapper
    if isinstance(remote_result.get("task"), dict):
        return remote_result["task"]
    if isinstance(remote_result.get("message"), dict):
        return remote_result["message"]
    if isinstance(remote_result.get("artifact"), dict):
        return {"artifacts": [remote_result["artifact"]]}

    return remote_result


def extract_primary_text(payload: dict[str, Any]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    texts: list[str] = []

    # 1) Prefer artifacts
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict):
                texts.extend(collect_texts_from_parts(artifact.get("parts")))

    # 2) Single artifact wrapper
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        texts.extend(collect_texts_from_parts(artifact.get("parts")))

    # 3) status.message.parts
    status = payload.get("status")
    if isinstance(status, dict):
        status_message = status.get("message")
        if isinstance(status_message, dict):
            texts.extend(collect_texts_from_parts(status_message.get("parts")))

    # 4) Direct Message payload
    texts.extend(collect_texts_from_parts(payload.get("parts")))

    message = payload.get("message")
    if isinstance(message, dict):
        texts.extend(collect_texts_from_parts(message.get("parts")))

    # 5) History fallback
    history = payload.get("history")
    if isinstance(history, list):
        for item in history:
            if isinstance(item, dict):
                texts.extend(collect_texts_from_parts(item.get("parts")))

    # De-duplicate while preserving order
    deduped: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if text not in seen:
            seen.add(text)
            deduped.append(text)

    if not deduped:
        return None

    return "\n\n".join(deduped)


def build_summary(
    normalized_task: str,
    remote_endpoint: str,
    remote_text: Optional[str],
    remote_result: Optional[dict[str, Any]] = None,
    router_context_id: Optional[str] = None,
    remote_context_id: Optional[str] = None,
) -> str:
    if remote_text:
        reply_text = remote_text
    else:
        reply_text = (
            json.dumps(remote_result, ensure_ascii=False, indent=2)
            if remote_result
            else "[no text returned]"
        )

    details = []
    if router_context_id:
        details.append(f"Router context ID: {router_context_id}")
    if remote_context_id:
        details.append(f"Remote context ID: {remote_context_id}")

    details_block = "\n".join(details)
    if details_block:
        details_block = f"{details_block}\n\n"

    return (
        f"Router agent normalized the request to: {normalized_task}\n\n"
        f"{details_block}"
        f"Remote agent endpoint: {remote_endpoint}\n\n"
        f"Remote agent reply:\n{reply_text}"
    )


def build_agent_card() -> dict[str, Any]:
    return {
        "name": "kagent_a2a_router",
        "description": "A simple A2A router that normalizes Kubernetes listing requests and delegates them to a remote kagent Kubernetes A2A agent.",
        "url": f"{PUBLIC_BASE_URL}/",
        "version": "0.6.4",
        "protocolVersion": "0.2.6",
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": "route-k8s-resource-list",
                "name": "Route Kubernetes resource list tasks",
                "description": "Converts simple user requests into normalized Kubernetes listing tasks and delegates them to a remote kagent A2A agent.",
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
        "kind": "task",
        "status": {
            "state": "completed",
            "message": {
                "role": "agent",
                "messageId": uuid4().hex,
                "parts": [{"kind": "text", "text": summary_text}],
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
        "kind": "task",
        "status": {
            "state": "failed",
            "message": {
                "role": "agent",
                "messageId": uuid4().hex,
                "parts": [{"kind": "text", "text": error_text}],
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


def build_status_update_event(
    task_id: str,
    context_id: str,
    state: str,
    final: bool,
    text: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "kind": "status-update",
        "taskId": task_id,
        "contextId": context_id,
        "final": final,
        "status": {
            "state": state,
            "message": {
                "role": "agent",
                "messageId": uuid4().hex,
                "parts": [{"kind": "text", "text": text}],
            },
        },
        "metadata": metadata or {},
    }


def rpc_result(req_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }


def stream_result(req_id: str, result: dict[str, Any]) -> dict[str, Any]:
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


def sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
