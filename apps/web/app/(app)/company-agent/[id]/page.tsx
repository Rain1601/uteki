import { CompanyDossierClient } from "./view";

export const dynamic = "force-dynamic";

/**
 * The dossier needs the caller's access token to fetch the run + artifacts
 * (cross-user runs 404 otherwise). The token lives in sessionStorage, which
 * is browser-only, so we pass run_id through and let the client component
 * do the fetch under proper auth. This avoids the prior SSR fetch silently
 * falling back to demo@local (which doesn't own most runs) and rendering
 * an empty shell.
 */
export default async function CompanyAgentDossierPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <CompanyDossierClient runId={id} />;
}
