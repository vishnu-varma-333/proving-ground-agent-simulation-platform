export type SimulationState = "pending" | "running" | "completed" | "failed";

export interface SuiteRow {
  id: string;
  name: string;
  created_at: string;
}

export interface RunRow {
  id: string;
  suite_id: string;
  suite_name: string;
  agent_version_id: string;
  priority: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  total: number;
  completed: number;
  failed: number;
  pending: number;
}

export interface SimulationResult {
  reply?: string;
  step_count?: number;
  checks_passed?: number;
  checks_total?: number;
  judge_resolved?: boolean;
  judge_score?: number;
  error?: string;
}

export interface SimulationRow {
  id: string;
  run_id: string;
  scenario_id: string;
  seed: number;
  state: SimulationState;
  worker_lease: string | null;
  tape_ref: string | null;
  result: SimulationResult | null;
  attempt: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  persona: string;
  goal: string;
  user_message: string;
  simulated_user: boolean;
}

export interface AgentVersionRow {
  id: string;
  image: string;
  git_sha: string;
  created_at: string;
}

export interface CheckResultRow {
  sim_id: string;
  description: string;
  service: string;
  passed: number;
  detail: string;
  recorded_at: string;
}

export interface JudgeScoreRow {
  sim_id: string;
  resolved: number;
  score: number;
  rationale: string;
  model: string;
  recorded_at: string;
}

export type StepKind = "model" | "tool" | "clock";

export interface StepRecord {
  seq: number;
  kind: StepKind;
  name: string;
  input_hash: string;
  output_hash: string;
  recorded_at: string;
}

export interface TapeManifest {
  run_id: string;
  agent_name: string;
  started_at: string;
  finished_at: string;
  step_count: number;
  steps: StepRecord[];
}
