import { RunEvalDemoClient } from "./view";

export const dynamic = "force-dynamic";

/**
 * /runs-eval/[id] — alignment demo for per-step eval on a run's detail page.
 *
 * Maps Anthropic's "demystifying evals for AI agents" framework onto the
 * run's actual structure:
 *
 *   • Each subagent step = its own outcome (artifact + rubric verdict)
 *   • Programmatic checks where deterministic (artifact present, citations
 *     resolved, JSON well-formed)
 *   • LLM rubric scoring per dimension (one rubric per gate, not one
 *     monolithic judge)
 *   • Inline annotator surface AT EACH STEP, not just on the run as a whole
 *   • Transcript metrics (cost / duration / tool calls) computed in code
 *
 * This is a DEMO: the inline 👍/👎/🚩 state lives in browser memory only;
 * nothing is persisted server-side. Once the layout is signed off we'll
 * design the (user_id, run_id, scope) feedback extension and the per-step
 * judge.
 */
export default async function RunEvalDemoPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <RunEvalDemoClient runId={id} />;
}
