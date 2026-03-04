import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Menu, MenuItem } from "../ui/Menu";
import Popover from "../ui/Popover";
import Avatar from "./Avatar";
import ProfileModal from "../profile/ProfileModal";
import { useTheme, type Theme } from "../../../theme/ThemeProvider";

type UserClaims = Record<string, unknown>;

type Props = {
  user: UserClaims;
  onReport: () => void;
  onAgentActivity: () => void;
  onSignOut: () => void;
};

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function resolveProvider(user: UserClaims): string {
  const direct = asString(user.provider) || asString(user.idp) || asString(user.identity_provider);
  if (direct) return direct;

  const issuer = asString(user.iss);
  if (issuer.includes("accounts.google.com")) return "google";
  if (issuer.includes("cognito-idp")) return "cognito";
  return "oidc";
}

function resolveProfile(user: UserClaims) {
  const profileNode = (user.profile as Record<string, unknown> | undefined) || {};
  const email =
    asString(user.email) ||
    asString(profileNode.email) ||
    asString(user.preferred_username) ||
    asString(user["cognito:username"]);
  const displayName =
    asString(user.name) ||
    asString(profileNode.name) ||
    asString(user.preferred_username) ||
    (email.includes("@") ? email.split("@")[0] : "User");
  const subject = asString(user.sub) || asString(user.subject) || asString(user.user_id);
  const provider = resolveProvider(user);
  // Avatar source resolution order: OIDC standard picture, nested profile picture, app-specific avatar fields.
  const picture =
    asString(user.picture) || asString(profileNode.picture) || asString(user.avatar_url) || asString(user.avatarUrl);

  return {
    displayName,
    email,
    subject,
    provider,
    picture,
  };
}

export default function UserMenu({ user, onReport, onAgentActivity, onSignOut }: Props) {
  const [open, setOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profile = useMemo(() => resolveProfile(user), [user]);
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
                onAgentActivity();
              }}
            >
              Agent activity (Ctrl/Cmd+Shift+A)
            </MenuItem>
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
