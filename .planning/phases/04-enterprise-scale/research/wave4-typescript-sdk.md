# Wave 4 Research: TypeScript Client SDK (T-4.13)

**Researched:** 2026-03-13
**Confidence:** HIGH
**Scope:** Project scaffolding, openapi-fetch + SSE streaming, test setup, CI pipeline

---

## 1. Orchestra API Surface (from source code)

The FastAPI server exposes 9 endpoints across 4 route groups, all under `/api/v1` prefix (except health):

### Health (no prefix)
| Method | Path | Response | Purpose |
|--------|------|----------|---------|
| GET | `/healthz` | `{status}` | Liveness probe |
| GET | `/readyz` | `{status}` | Readiness probe (checks event store) |

### Runs (`/api/v1/runs`)
| Method | Path | Request | Response | Purpose |
|--------|------|---------|----------|---------|
| POST | `/runs` | `RunCreate` | `RunResponse` (202) | Create & start workflow |
| GET | `/runs` | — | `RunStatus[]` | List all runs |
| GET | `/runs/{run_id}` | — | `RunStatus` | Get run status |
| POST | `/runs/{run_id}/resume` | `ResumeRequest` | `RunResponse` | Resume interrupted run |

### Streams (`/api/v1/runs`)
| Method | Path | Response | Purpose |
|--------|------|----------|---------|
| GET | `/runs/{run_id}/stream` | SSE EventSource | Real-time event stream |

### Graphs (`/api/v1/graphs`)
| Method | Path | Response | Purpose |
|--------|------|----------|---------|
| GET | `/graphs` | `GraphInfo[]` | List registered graphs |
| GET | `/graphs/{name}` | `GraphInfo` | Graph detail + Mermaid diagram |

### Key Models (Pydantic)
- **RunCreate**: `{graph_name, input: {}, config: {}}`
- **RunResponse**: `{run_id, status, graph_name, created_at}`
- **RunStatus**: `{run_id, status, created_at, completed_at?, event_count}`
- **GraphInfo**: `{name, nodes[], edges[], entry_point, mermaid}`
- **ResumeRequest**: `{state_updates: {}}`
- **ErrorResponse**: `{detail, error_type}`

### SSE Event Types
The stream endpoint emits events with types from `event.event_type.value`. Events include:
- `config` — initial retry directive
- `ping` — heartbeat (on timeout)
- `done` — terminal event with `{status}`
- Workflow events — `model_dump_json()` payload with `sequence` ID
- Supports reconnection via `Last-Event-ID` header (replays from EventStore)

---

## 2. Recommended Stack

| Tool | Version | Purpose |
|------|---------|---------|
| `openapi-typescript` | `^7.x` | Generate TS types from OpenAPI spec |
| `openapi-fetch` | `^0.17.x` | Type-safe fetch wrapper (~6kb) |
| `fetch-event-stream` | `^0.1.x` | SSE ReadableStream → async iterator (~741 bytes) |
| `typescript` | `^5.7` | Compiler |
| `tsup` | `^8.x` | Build (dual ESM + CJS output) |
| `vitest` | `^4.x` | Test runner |
| `msw` | `^2.x` | Network-level mocking for tests |

### Why openapi-fetch over alternatives
- **Zero runtime cost** — thin wrapper around native fetch
- **6kb** — smallest type-safe client
- **Auto-typed** from OpenAPI spec, no manual types
- **Works everywhere** — browser, Node, Deno, Bun
- Alternative `orval` generates React Query hooks — too opinionated for a general SDK

### SSE Caveat
`openapi-fetch`'s `parseAs: "stream"` returns raw bytes, not parsed SSE. The SSE endpoint should use native `fetch` + `fetch-event-stream` (or `EventSource` for browsers), bypassing openapi-fetch for that one endpoint.

---

## 3. Recommended Project Structure

```
sdk/typescript/
  package.json
  tsconfig.json
  tsup.config.ts
  vitest.config.ts
  scripts/
    extract-openapi.py      # Dumps FastAPI OpenAPI spec to JSON
  src/
    index.ts                 # Main entry — re-exports client + types
    client.ts                # OrchestraClient class wrapping openapi-fetch
    stream.ts                # SSE streaming helper (fetch + fetch-event-stream)
    types/
      openapi.d.ts           # Auto-generated from OpenAPI spec (gitignored)
      events.ts              # SSE event type discriminated union
  tests/
    client.test.ts           # REST endpoint tests (vitest + msw)
    stream.test.ts           # SSE streaming tests
    mocks/
      handlers.ts            # MSW request handlers
      server.ts              # MSW server setup
  README.md
```

---

## 4. Key Implementation Patterns

### 4a. Client (REST endpoints)

```typescript
import createClient from "openapi-fetch";
import type { paths } from "./types/openapi";

export function createOrchestraClient(baseUrl: string) {
  const client = createClient<paths>({ baseUrl });

  return {
    // Runs
    createRun: (graphName: string, input?: Record<string, unknown>) =>
      client.POST("/api/v1/runs", {
        body: { graph_name: graphName, input: input ?? {}, config: {} },
      }),
    listRuns: () => client.GET("/api/v1/runs"),
    getRunStatus: (runId: string) =>
      client.GET("/api/v1/runs/{run_id}", { params: { path: { run_id: runId } } }),
    resumeRun: (runId: string, stateUpdates?: Record<string, unknown>) =>
      client.POST("/api/v1/runs/{run_id}/resume", {
        params: { path: { run_id: runId } },
        body: { state_updates: stateUpdates ?? {} },
      }),

    // Graphs
    listGraphs: () => client.GET("/api/v1/graphs"),
    getGraph: (name: string) =>
      client.GET("/api/v1/graphs/{name}", { params: { path: { name } } }),

    // Health
    healthz: () => client.GET("/healthz"),
    readyz: () => client.GET("/readyz"),
  };
}
```

### 4b. SSE Streaming (separate from openapi-fetch)

```typescript
import { events } from "fetch-event-stream";

export async function* streamRunEvents(
  baseUrl: string,
  runId: string,
  options?: { lastEventId?: string; signal?: AbortSignal }
) {
  const headers: Record<string, string> = {};
  if (options?.lastEventId) {
    headers["Last-Event-ID"] = options.lastEventId;
  }

  const response = await fetch(`${baseUrl}/api/v1/runs/${runId}/stream`, {
    headers,
    signal: options?.signal,
  });

  if (!response.ok) throw new Error(`Stream failed: ${response.status}`);

  for await (const event of events(response, options?.signal)) {
    if (event.event === "done") {
      yield { type: "done" as const, data: JSON.parse(event.data ?? "{}") };
      break;
    }
    if (event.event === "ping") continue;

    yield {
      type: event.event ?? "unknown",
      data: JSON.parse(event.data ?? "{}"),
      id: event.id,
    };
  }
}
```

### 4c. Unit Testing SSE with MSW (Mock Service Worker)

To test the streaming client without a live server, use MSW's `HttpResponse` with a `ReadableStream`:

```typescript
import { http, HttpResponse } from "msw";

export const handlers = [
  http.get("/api/v1/runs/:runId/stream", ({ params }) => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: ping\ndata: {}\n\n"));
        controller.enqueue(encoder.encode("event: update\ndata: {\"status\":\"running\"}\n\n"));
        controller.enqueue(encoder.encode("event: done\ndata: {\"status\":\"success\"}\n\n"));
        controller.close();
      },
    });

    return new HttpResponse(stream, {
      headers: { "Content-Type": "text/event-stream" },
    });
  }),
];
```

### 4d. Middleware and Reconnection

`openapi-fetch` supports middleware for injecting authentication headers:

```typescript
const client = createClient<paths>({ baseUrl });
client.use({
  onRequest({ request }) {
    request.headers.set("Authorization", `Bearer ${token}`);
  },
});
```

For SSE, `fetch-event-stream` handles the low-level `ReadableStream` parsing, but the SDK must manage the `Last-Event-ID` state and retry logic (e.g., using exponential backoff) for production robustness.

---

## 5. Build Configuration

### tsup.config.ts (Refined)
```typescript
import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm", "cjs"],
  dts: true,
  splitting: true, // Enabled for better tree-shaking
  sourcemap: true,
  minify: true,
  clean: true,
  target: "es2022",
  outDir: "dist",
});
```

### package.json (key fields)
```json
{
  "name": "@orchestra/sdk",
  "version": "0.1.0",
  "type": "module",
  "main": "./dist/index.cjs",
  "module": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "import": "./dist/index.js",
      "require": "./dist/index.cjs",
      "types": "./dist/index.d.ts"
    }
  },
  "engines": { "node": ">=18" },
  "scripts": {
    "generate": "python scripts/extract-openapi.py && npx openapi-typescript openapi.json -o src/types/openapi.d.ts",
    "build": "npm run generate && tsup",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

---

## 6. CI Pipeline

The OpenAPI spec is generated at runtime by FastAPI, so CI needs a Python step:

```yaml
# In GitHub Actions
- name: Generate OpenAPI types
  run: |
    cd sdk/typescript
    python scripts/extract-openapi.py   # outputs openapi.json
    npx openapi-typescript openapi.json -o src/types/openapi.d.ts

- name: Build & Test SDK
  run: |
    cd sdk/typescript
    npm ci
    npm run build
    npm test
```

### scripts/extract-openapi.py
```python
"""Extract OpenAPI spec from Orchestra FastAPI app."""
import json
from orchestra.server.app import create_app

app = create_app()
with open("openapi.json", "w") as f:
    json.dump(app.openapi(), f, indent=2)
```

---

## 7. Open Questions

| Question | Impact | Recommendation |
|----------|--------|---------------|
| NPM scope: `@orchestra/sdk` vs `orchestra-sdk` | Publishing | Use `@orchestra/sdk` if org scope is available |
| Node.js minimum version | Compatibility | `>=18` (Node 16 is EOL) |
| SSE event type enumeration | Type safety | Define discriminated union from actual event types |
| OpenAPI 3.0 vs 3.1 for SSE | Schema accuracy | FastAPI generates 3.1; SSE endpoint won't have response schema — handle manually |
| Browser `EventSource` vs `fetch` | API surface | Offer both: `fetch-event-stream` for Node, optional `EventSource` adapter for browsers |

---

## 8. Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| API surface | HIGH | Read directly from source code (9 endpoints, 6 models) |
| openapi-fetch stack | HIGH | Well-documented, widely used, recent releases |
| SSE streaming | HIGH | Orchestra streaming code read; fetch-event-stream is minimal and correct |
| Build tooling (tsup) | HIGH | Standard dual-publish pattern |
| Test setup (vitest+msw) | MEDIUM-HIGH | Standard but SSE mocking needs ReadableStream |
| CI pipeline | MEDIUM | extract-openapi.py pattern works but cross-language CI adds complexity |

**Overall: ~85% ready for implementation.** Remaining 15% is SSE event type enumeration (need to catalog all event_type enum values) and CI integration testing.
