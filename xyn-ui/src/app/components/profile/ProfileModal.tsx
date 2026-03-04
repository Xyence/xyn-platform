type ProfileData = {
  displayName: string;
  email: string;
  provider: string;
  subject: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
  profile: ProfileData;
};

export default function ProfileModal({ open, onClose, profile }: Props) {
  if (!open) return null;

  return (
    <div className="overlay-backdrop" onClick={onClose}>
      <section className="overlay-card profile-modal" onClick={(event) => event.stopPropagation()}>
        <div className="card-header">
          <h3>Profile</h3>
          <button type="button" className="ghost" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="profile-grid">
          <div>
            <div className="label">Display name</div>
            <div>{profile.displayName || "-"}</div>
          </div>
          <div>
            <div className="label">Email</div>
            <div>{profile.email || "-"}</div>
          </div>
          <div>
            <div className="label">Provider</div>
            <div>{profile.provider || "-"}</div>
          </div>
          <div>
            <div className="label">Subject (sub)</div>
            <div className="profile-subject">{profile.subject || "-"}</div>
            {profile.subject && (
              <button
                type="button"
                className="ghost"
                onClick={() => void navigator.clipboard.writeText(profile.subject)}
              >
                Copy ID
              </button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
