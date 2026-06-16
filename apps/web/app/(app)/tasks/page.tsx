import { TaskFeedView } from "@/components/tasks/TaskFeedView";

/**
 * /tasks — cross-trigger "全部" view.
 *
 * The 3-column shell (left trigger sidebar) is owned by
 * ``layout.tsx``. This page just renders the feed view with
 * triggerId=null, which makes the component hit ``GET /api/news`` for
 * the dedup'd merged feed.
 */
export default function TasksAllPage() {
  return <TaskFeedView triggerId={null} />;
}
