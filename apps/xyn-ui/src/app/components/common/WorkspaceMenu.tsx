import { useMemo, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { Menu } from "../ui/Menu";
import Popover from "../ui/Popover";

type WorkspaceOption = {
  id: string;
  name: string;
};

type Props = {
  activeWorkspaceId: string;
  workspaces: WorkspaceOption[];
  onWorkspaceChange: (workspaceId: string) => void;
};

export default function WorkspaceMenu({ activeWorkspaceId, workspaces, onWorkspaceChange }: Props) {
  const [open, setOpen] = useState(false);
  const activeWorkspaceName = useMemo(
    () => workspaces.find((workspace) => workspace.id === activeWorkspaceId)?.name || "",
    [activeWorkspaceId, workspaces],
  );

  if (!activeWorkspaceName) return null;

  return (
    <div className="user-menu-wrap workspace-menu-wrap">
      <button
        type="button"
        id="workspace-selector"
        className="ghost user-menu-trigger workspace-menu-trigger"
        aria-label="Workspace"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="workspace-menu-trigger-label">{activeWorkspaceName}</span>
        <ChevronDown size={14} />
      </button>

      <Popover open={open} onClose={() => setOpen(false)} className="user-menu-popover workspace-menu-popover">
        <Menu>
          {workspaces.map((workspace) => (
            <button
              key={workspace.id}
              type="button"
              className="xyn-menu-item"
              aria-current={workspace.id === activeWorkspaceId ? "true" : undefined}
              onClick={() => {
                setOpen(false);
                onWorkspaceChange(workspace.id);
              }}
            >
              <span className="workspace-menu-item-label">{workspace.name}</span>
              {workspace.id === activeWorkspaceId ? <Check size={14} aria-hidden="true" /> : null}
            </button>
          ))}
        </Menu>
      </Popover>
    </div>
  );
}
