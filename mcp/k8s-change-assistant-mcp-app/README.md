# Kubernetes Change Assistant MCP App

A minimal MCP Apps scaffold: implement own narrow but realistic MCP Apps case.

This project follows the official **MCP Apps = Tool + UI Resource** pattern. The app opens an interactive UI inside an MCP host and exposes a safe **dry-run** flow for reviewing a Kubernetes deployment change.

## What this demo does

- opens an MCP App view with `open-k8s-change-assistant`
- renders a sandboxed interactive UI
- calls server-side tools from the UI to refresh data
- shows:
  - deployment status
  - pod list
  - recent events
  - change summary
  - dry-run patch preview

## Why this is a good certification case

It is **narrow**, **practical**, and easy to defend:

- it uses the official MCP Apps architecture
- it demonstrates tool calls from the UI
- it maps to a real platform-engineering workflow
- it is safe because it does **not** perform a live rollout

## Project structure

```text
k8s-change-assistant-mcp-app/
├── main.ts
├── mcp-app.html
├── package.json
├── README.md
├── server.ts
├── src/
│   └── mcp-app.ts
├── tsconfig.json
├── tsconfig.server.json
└── vite.config.ts
```

## Prerequisites

- Node.js 18+
- npm
- an MCP Apps-capable host or MCP Inspector for testing

## Install

```bash
npm install
```

## Run in HTTP mode

```bash
npm start
```

By default the server starts on:

```text
http://localhost:3001/mcp
```

## Run in stdio mode

```bash
npm run start:stdio
```

## Build the bundled UI

```bash
npm run build
```

The single-file app view is produced at:

```text
dist/mcp-app.html
```

## Demo flow

1. Open the tool `open-k8s-change-assistant`
2. The host renders the UI resource `ui://k8s-change-assistant/mcp-app.html`
3. The app shows a deployment change form with mock defaults
4. Click:
   - **Refresh all context**
   - **Generate risk summary**
   - **Run dry-run preview**
5. Explain that the current code uses mock data and can later be wired to real Kubernetes APIs

## Current implementation boundaries

This scaffold intentionally uses **mock Kubernetes data** so the demo is stable and safe.

Replace the helper functions in `server.ts` with:

- Kubernetes client library calls
- `kubectl` execution
- internal platform APIs
- optional Elicitation and Sampling integration

## Suggested next steps

- connect `server.ts` to a real cluster in read-only mode
- add Elicitation for missing fields like environment or approval reason
- add Sampling for a richer AI-generated rollout summary
- add authentication and per-environment access control
- add a real dry-run integration against Kubernetes manifests

## Notes for presentation

Use this phrasing during the demo:

> This MCP App is a Kubernetes Change Assistant. It opens an interactive dry-run workflow inside the MCP host, lets the user inspect deployment context, and safely prepares a rollout decision without applying changes to the cluster.

## Sources

- MCP Apps overview: https://modelcontextprotocol.io/extensions/apps/overview
- MCP Apps build guide: https://modelcontextprotocol.io/extensions/apps/build
- MCP Apps quickstart: https://apps.extensions.modelcontextprotocol.io/api/documents/Quickstart.html
- MCP tools specification: https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- MCP extension support matrix: https://modelcontextprotocol.io/extensions/client-matrix
