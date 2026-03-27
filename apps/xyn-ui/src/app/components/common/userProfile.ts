export type UserClaims = Record<string, unknown>;

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

export function resolveUserProfile(user: UserClaims) {
  const profileNode = (user.profile as Record<string, unknown> | undefined) || {};
  const email =
    asString(user.email)
    || asString(profileNode.email)
    || asString(user.preferred_username)
    || asString(user["cognito:username"]);
  const displayName =
    asString(user.name)
    || asString(profileNode.name)
    || asString(user.preferred_username)
    || (email.includes("@") ? email.split("@")[0] : "User");
  const subject = asString(user.sub) || asString(user.subject) || asString(user.user_id);
  const provider = resolveProvider(user);
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
