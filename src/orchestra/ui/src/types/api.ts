/** API response types matching Python Pydantic models. */

export interface RunStatus {
  run_id: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  event_count: number;
  workflow_name: string;
}

export interface RunResponse {
  run_id: string;
  status: string;
  graph_name: string;
  created_at: string;
}

export interface GraphEdge {
  type: 'Edge' | 'ConditionalEdge' | 'ParallelEdge';
  source: string;
  target: string | string[];
}

export interface GraphInfo {
  name: string;
  nodes: string[];
  edges: GraphEdge[];
  entry_point: string;
  mermaid: string;
}

export interface EventItem {
  event_id: string;
  run_id: string;
  event_type: string;
  sequence: number;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface RunState {
  run_id: string;
  state: Record<string, unknown>;
  event_count: number;
}

export interface CostBreakdown {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  call_count: number;
}

export interface RunCost {
  run_id: string;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  call_count: number;
  by_model: Record<string, CostBreakdown>;
  by_agent: Record<string, CostBreakdown>;
}
