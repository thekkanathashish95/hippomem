/** Map internal op keys to human-readable labels for the Inspector UI */
export const OP_LABELS: Record<string, string> = {
  continuation_check: 'C1: Continuation Check',
  synthesis: 'Synthesis',
  detect_drift: 'Detect Drift',
  extract_event_update: 'Extract Update',
  should_create_new_event: 'Create Check',
  maybe_append_to_ets: 'ETS Append',
  generate_new_event: 'Generate Event',
  extract_entities: 'Entity Extract',
  disambiguate_entity: 'Entity Disambiguate',
  extract_self_candidates: 'Self Extract',
  generate_cluster_summary: 'Cluster Summary',
  generate_identity_summary: 'Identity Summary',
  update_entity_profile: 'Entity Profile Update',
}

export function getOpLabel(op: string): string {
  return OP_LABELS[op] ?? op
}
