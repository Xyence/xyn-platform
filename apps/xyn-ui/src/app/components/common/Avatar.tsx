import { useMemo, useState } from "react";

export type AvatarSize = "sm" | "md" | "lg";

type AvatarProps = {
  src?: string;
  name?: string;
  email?: string;
  identityKey?: string;
  size?: AvatarSize;
  className?: string;
};

function asSafeText(value?: string): string {
  return (value || "").trim();
}

export function computeInitials(name?: string, email?: string): string {
  const safeName = asSafeText(name);
  if (safeName) {
    const parts = safeName.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
    }
    return (parts[0]?.slice(0, 2) || "U").toUpperCase();
  }

  const safeEmail = asSafeText(email);
  if (safeEmail.includes("@")) {
    const local = safeEmail.split("@")[0];
    const segments = local.split(/[._-]+/).filter(Boolean);
    if (segments.length >= 2) {
      return `${segments[0][0] ?? ""}${segments[1][0] ?? ""}`.toUpperCase();
    }
    return (local.slice(0, 2) || "U").toUpperCase();
  }
  return "U";
}

export function colorFromIdentity(identity?: string): string {
  const input = asSafeText(identity) || "xyn-user";
  let hash = 0;
  for (let i = 0; i < input.length; i += 1) {
    hash = (hash << 5) - hash + input.charCodeAt(i);
    hash |= 0;
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 45% 42%)`;
}

export default function Avatar({
  src,
  name,
  email,
  identityKey,
  size = "sm",
  className = "",
}: AvatarProps) {
  const [failed, setFailed] = useState(false);
  const initials = useMemo(() => computeInitials(name, email), [name, email]);
  const background = useMemo(() => colorFromIdentity(identityKey || email || name), [identityKey, email, name]);
  const showImage = Boolean(src) && !failed;

  return (
    <span className={`xyn-avatar xyn-avatar-${size} ${className}`.trim()} style={{ backgroundColor: background }}>
      {showImage ? (
        <img
          src={src}
          alt={name ? `${name} avatar` : "User avatar"}
          onError={() => setFailed(true)}
          referrerPolicy="no-referrer"
        />
      ) : (
        <span className="xyn-avatar-fallback" aria-hidden="true">
          {initials}
        </span>
      )}
    </span>
  );
}
