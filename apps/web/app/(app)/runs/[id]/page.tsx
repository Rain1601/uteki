import Link from "next/link";
import { getRun } from "@/lib/api";
import { RunDetailView } from "./view";
import { PageContainer } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";

export const dynamic = "force-dynamic";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  try {
    const run = await getRun(id);
    return <RunDetailView run={run} />;
  } catch (e) {
    return (
      <PageContainer>
        <Link
          href="/runs"
          className="font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--ink-muted)] hover:text-[var(--ink)]"
        >
          ← back to runs
        </Link>
        <Card className="mt-4 border-[color-mix(in_srgb,var(--loss)_40%,transparent)] p-4 text-[12px] text-[var(--loss)]">
          ⚠ 加载 run 失败：{(e as Error).message}
        </Card>
      </PageContainer>
    );
  }
}
