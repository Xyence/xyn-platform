import { useSearchParams } from "react-router-dom";
import Tabs from "../components/ui/Tabs";
import IdentityProvidersPage from "./IdentityProvidersPage";
import OidcAppClientsPage from "./OidcAppClientsPage";

type IdentityTab = "identity-providers" | "oidc-app-clients";

const IDENTITY_TABS: Array<{ value: IdentityTab; label: string }> = [
  { value: "identity-providers", label: "Identity Providers" },
  { value: "oidc-app-clients", label: "OIDC App Clients" },
];

export default function IdentityConfigurationPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = String(searchParams.get("tab") || "").trim();
  const activeTab: IdentityTab = (IDENTITY_TABS.find((item) => item.value === tabParam)?.value || "identity-providers") as IdentityTab;

  const updateTab = (next: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Identity Configuration</h2>
          <p className="muted">Manage identity providers and OIDC app clients.</p>
        </div>
      </div>
      <div className="page-tabs">
        <Tabs
          ariaLabel="Identity Configuration tabs"
          value={activeTab}
          onChange={updateTab}
          options={IDENTITY_TABS.map((item) => ({ value: item.value, label: item.label }))}
        />
      </div>
      {activeTab === "identity-providers" ? <IdentityProvidersPage /> : <OidcAppClientsPage />}
    </>
  );
}
