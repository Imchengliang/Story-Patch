export type StuckCharacter = { name: string; function: string };

export type StuckPoint = {
  story_state: string;
  genre: string;
  characters: StuckCharacter[];
  current_node: string;
  stuck_question: string;
  constraints: string[];
  desired_effect: string;
  narrative_functions: string[];
  value_polarity: string;
};

export type Precedent = {
  kind: string;
  scene_id: string;
  work_title: string;
  scene_heading: string;
  score: number;
  excerpt: string;
  highlight: string | null;
  reasons: string[];
};

export type Suggestion = {
  next_node: string;
  character_behavior_logic: string;
  emotional_tone: string;
  corpus_reference: string;
  reference_quote: string | null;
  transfer_rationale: string;
  fit_score: number;
  novelty_score: number;
};

export type Beat = {
  index: number;
  next_node: string;
  character_behavior_logic: string;
  emotional_tone: string;
  corpus_reference: string;
  reference_quote: string | null;
  transfer_rationale: string;
};

export type BeatSequence = {
  suggestion_id: string;
  beats: Beat[];
  risk: string;
  still_unresolved: string;
};

export type SuggestResult = {
  provider: string;
  model: string;
  stuck_point: StuckPoint | null;
  precedents: Precedent[];
  suggestions: Suggestion[];
  story_facts: string[];
  story_status?: "ready" | "building" | "absent";
};

export type UsageSnapshot = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  calls: number;
};

export type BudgetLimits = { max_tokens: number; max_cost_usd: number };

export type BudgetEvent = UsageSnapshot & { limits: BudgetLimits };

export type AssistantPayload = {
  plan?: string[];
  story_facts?: string[];
  stuck_point?: StuckPoint | null;
  precedents?: Precedent[];
  suggestions?: Suggestion[];
  beats?: Array<BeatSequence | null>;
  usage?: BudgetEvent;
  used_fallback?: boolean;
  error?: string;
};

export type ThreadOut = {
  id: string;
  title: string;
  story_id: string | null;
  archived: boolean;
  active_stuck: StuckPoint | null;
  created_at: string;
  updated_at: string;
};

export type MessageOut = {
  id: string;
  seq: number;
  role: string;
  content: string;
  payload: AssistantPayload | null;
  run_id: string | null;
};

export type LastRun = {
  run_id: string;
  status: string;
  task: string;
  error: string | null;
};

export type ThreadDetail = {
  thread: ThreadOut;
  messages: MessageOut[];
  last_run: LastRun | null;
};

export type ThreadUsage = {
  thread: UsageSnapshot;
  runs: Array<UsageSnapshot & { run_id: string; task: string }>;
  limits: { max_tokens: number | null; max_cost_usd: number | null };
};

export type ReplayCheck = {
  tool: string;
  equal: boolean;
  comparable: boolean;
  detail: string;
};

export type ReplayReport = {
  source_run_id: string;
  ok: boolean;
  error: string;
  checks: ReplayCheck[];
};

export type FeedbackSummary = {
  total: number;
  decisions: Record<string, number>;
  reasons: Record<string, number>;
  adoption_rate: number;
};

export type LiveRun = {
  runId: string | null;
  plan: string[];
  stage: string | null;
  stuck: StuckPoint | null;
  precedents: Precedent[];
  suggestions: Suggestion[];
  storyFacts: string[];
  usage: UsageSnapshot | null;
  limits: BudgetLimits | null;
  error: string | null;
  done: boolean;
};
