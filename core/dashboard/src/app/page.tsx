import AgentStatusPanel from "./components/AgentStatusPanel";
import TaskQueueView    from "./components/TaskQueueView";
import EventFeed        from "./components/EventFeed";
import CampaignStats    from "./components/CampaignStats";
import CommandInput     from "./components/CommandInput";

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-6">
      {/* Row 1 — Agent status (full width) */}
      <AgentStatusPanel />

      <div className="w-full border-t border-zinc-900" />

      {/* Row 2 — Task queue (left) + Event feed (right) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TaskQueueView />
        <EventFeed />
      </div>

      <div className="w-full border-t border-zinc-900" />

      {/* Row 3 — Campaign stats (left) + Command input (right) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CampaignStats />
        <CommandInput />
      </div>
    </div>
  );
}
