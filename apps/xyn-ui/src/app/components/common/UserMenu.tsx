import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Menu, MenuItem } from "../ui/Menu";
import Popover from "../ui/Popover";
import Avatar from "./Avatar";
import ProfileModal from "../profile/ProfileModal";
import { useTheme, type Theme } from "../../../theme/ThemeProvider";
import { resolveUserProfile, type UserClaims } from "./userProfile";

type Props = {
  user: UserClaims;
  onReport: () => void;
  onSignOut: () => void;
};

export default function UserMenu({ user, onReport, onSignOut }: Props) {
  const [open, setOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profile = useMemo(() => resolveUserProfile(user), [user]);
  const { theme, setTheme } = useTheme();

  const themeOptions: Array<{ value: Theme; label: string }> = [
    { value: "light", label: "Light" },
    { value: "dim", label: "Dim" },
    { value: "dark", label: "Dark" },
  ];

  return (
    <>
      <div className="user-menu-wrap">
        <button
          type="button"
          className="ghost user-menu-trigger"
          aria-label="User menu"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <Avatar
            size="sm"
            src={profile.picture || undefined}
            name={profile.displayName}
            email={profile.email}
            identityKey={profile.subject || profile.email}
          />
          <ChevronDown size={14} />
        </button>

        <Popover open={open} onClose={() => setOpen(false)} className="user-menu-popover">
          <Menu>
            <MenuItem
              onSelect={() => {
                setOpen(false);
                setProfileOpen(true);
              }}
            >
              Profile
            </MenuItem>
            <button type="button" className="xyn-menu-item disabled" disabled>
              Account / Preferences (coming soon)
            </button>
            <div className="xyn-menu-theme">
              <div className="xyn-menu-theme-label">Theme</div>
              <div className="xyn-theme-segmented" role="radiogroup" aria-label="Theme">
                {themeOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={theme === option.value}
                    className={`xyn-theme-option ${theme === option.value ? "selected" : ""}`}
                    onClick={() => setTheme(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <p className="xyn-menu-theme-help">Light: bright. Dim: slate/navy (recommended). Dark: near-black.</p>
            </div>
            <div className="xyn-menu-divider" />
            <MenuItem
              onSelect={() => {
                setOpen(false);
                onReport();
              }}
            >
              Report (Ctrl/Cmd+Shift+B)
            </MenuItem>
            <MenuItem
              onSelect={() => {
                setOpen(false);
                onSignOut();
              }}
            >
              Sign out
            </MenuItem>
          </Menu>
        </Popover>
      </div>

      <ProfileModal
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
        profile={{
          displayName: profile.displayName,
          email: profile.email,
          provider: profile.provider,
          subject: profile.subject,
        }}
      />
    </>
  );
}
