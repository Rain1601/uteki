import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { PageContainer } from "@/components/ui/PageHeader";
import { getRun } from "@/lib/api";
import { CompanyDossierView } from "./view";

export const dynamic = "force-dynamic";

export default async function CompanyAgentDossierPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  try {
    const run = await getRun(id);
    return <CompanyDossierView run={run} />;
  } catch (e) {
    return (
      <PageContainer>
        <Link
          href="/company-agent"
          className="font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--ink-muted)] hover:text-[var(--ink)]"
        >
          ← back to company agent
        </Link>
        <Card className="mt-4 border-[color-mix(in_srgb,var(--loss)_40%,transparent)] p-4 text-[12px] text-[var(--loss)]">
          加载公司档案失败：{(e as Error).message}
        </Card>
      </PageContainer>
    );
  }
}
