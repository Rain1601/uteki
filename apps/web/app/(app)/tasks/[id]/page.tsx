"use client";

import { useParams } from "next/navigation";
import { TaskFeedView } from "@/components/tasks/TaskFeedView";

/**
 * /tasks/[id] — per-trigger feed view.
 *
 * The 3-column shell (left trigger sidebar with name / condition /
 * cadence + the highlight of the active trigger) is owned by
 * ``layout.tsx``. This page just routes the trigger id from the URL
 * segment into the shared ``TaskFeedView`` component, which hits
 * ``GET /api/triggers/{id}/news`` for the scoped feed.
 */
export default function TasksPerTriggerPage() {
  const params = useParams<{ id: string }>();
  const triggerId = params.id;
  return <TaskFeedView triggerId={triggerId} />;
}
