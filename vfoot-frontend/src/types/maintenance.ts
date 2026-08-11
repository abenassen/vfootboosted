/** Site maintenance: how the server is, and what is waiting for a yes or a no.
 *
 *  Staff-only. This mirrors realdata/api/views.py — see
 *  vfoot-backend/docs/maintenance_agent_plan.md for why the agent only ever
 *  proposes and never acts. */

export type MaintenanceVerdict = 'ok' | 'warn' | 'alarm';

export type MaintenanceCheckLevel = 'info' | 'warn' | 'alarm';

export interface MaintenanceCheck {
  level: MaintenanceCheckLevel;
  code: string;
  message: string;
}

/** The closed set. The server re-validates whatever arrives against it twice —
 *  once in Python and once in the privileged shell wrapper — so this type is a
 *  convenience for the UI, never a control. */
export type ProposalKind =
  | 'restart_unit'
  | 'rerun_command'
  | 'clear_cache_file'
  | 'apply_patch'
  | 'none';

export type ProposalStatus =
  | 'proposed'
  | 'approved'
  | 'rejected'
  | 'done'
  | 'failed'
  | 'refused';

export interface ProposalBrief {
  id: number;
  kind: ProposalKind;
  payload: Record<string, unknown>;
  status: ProposalStatus;
  /** apply_patch is true here at every setting: no auto tier ever runs a patch. */
  needs_human: boolean;
  created_at: string;
  summary: string;
  rationale: string;
}

export interface ProposalDetail extends ProposalBrief {
  evidence: Record<string, unknown>;
  diagnosis: string;
  agent_cmd: string;
  result: string;
  decided_at: string | null;
  /** Present only for apply_patch; capped server-side, and the cut is stated in
   *  the text itself rather than left silent. */
  diff: string | null;
}

export interface MaintenanceRunBrief {
  id: number;
  started_at: string;
  trigger: 'alarm' | 'weekly' | 'manual';
  summary: string;
  ok: boolean | null;
  error: string;
}

export interface MaintenanceState {
  verdict: MaintenanceVerdict;
  checks: MaintenanceCheck[];
  pending: ProposalBrief[];
  runs: MaintenanceRunBrief[];
  auto_enabled: boolean;
}

export interface DecideResponse {
  id: number;
  status: ProposalStatus;
  note: string;
}
