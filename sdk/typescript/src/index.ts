import createClient from "openapi-fetch";
import { fetchEventStream } from "fetch-event-stream";
import type { paths } from "./types";

export interface ClientOptions {
  baseUrl: string;
  apiKey?: string;
}

export class OrchestraClient {
  private client: ReturnType<typeof createClient<paths>>;

  constructor(options: ClientOptions) {
    this.client = createClient<paths>({ 
      baseUrl: options.baseUrl 
    });

    if (options.apiKey) {
      this.client.use({
        onRequest({ request }) {
          request.headers.set("Authorization", `Bearer ${options.apiKey}`);
          return request;
        },
      });
    }
  }

  /**
   * Start a new workflow run and return the run ID.
   */
  async startRun(graphName: string, input: any) {
    const { data, error } = await this.client.POST("/api/v1/runs", {
      body: {
        graph_name: graphName,
        input_data: input,
      },
    });

    if (error) throw new Error(`Failed to start run: ${JSON.stringify(error)}`);
    return data;
  }

  /**
   * Stream events from an active run using SSE.
   */
  async *streamRunEvents(runId: string, signal?: AbortSignal) {
    const url = new URL(`/api/v1/runs/${runId}/stream`, (this.client as any).baseUrl);
    
    const stream = await fetchEventStream(url.toString(), {
      signal,
      headers: {
        "Accept": "text/event-stream",
        ...(this.client as any).headers,
      }
    });

    for await (const event of stream) {
      if (event.event === "ping") continue;
      
      try {
        const data = JSON.parse(event.data);
        yield {
          type: event.event,
          data,
          id: event.id,
        };
      } catch (e) {
        console.warn("Failed to parse SSE event data", e);
      }
    }
  }
}
