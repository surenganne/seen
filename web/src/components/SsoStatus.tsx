import { Link } from "react-router-dom";
import { useTeamSso } from "../api/hooks";
import { Badge, Card, Loading, Note } from "./ui";

function Row({ k, v }: { k: string; v: string }) {
  return <div style={{ display: "contents" }}><dt>{k}</dt><dd className="mono">{v}</dd></div>;
}

/** Read-only. SSO is set on the team server (environment variables), never from a dashboard: a page that can change
 *  the issuer can change who is trusted to sign in. */
export function SsoStatus() {
  const { data: s, isLoading, error } = useTeamSso();
  if (isLoading) return <Card title="Single sign-on (SSO)"><Loading what="Checking SSO" rows={2} /></Card>;
  if (error || !s) return <Card title="Single sign-on (SSO)"><Note tone="warning">SSO status could not be read.</Note></Card>;
  const badge = s.sso === "configured" ? <Badge tone="good">configured</Badge>
    : s.sso === "off" ? <Badge tone="neutral">not set up on the server</Badge>
    : s.sso === "provider_unavailable" ? <Badge tone="warning">provider unavailable</Badge>
    : <Badge tone="neutral">unknown</Badge>;
  const v = s.server;
  return (
    <Card title="Single sign-on (SSO)" aside={badge}>
      <div className="stack" data-testid="sso-status">
        {s.state !== "ok" && <Note tone="warning" testId="sso-state">{s.reason}</Note>}
        {s.sso === "provider_unavailable" && <Note tone="warning">The team server could not reach the identity provider. Existing keys keep working; new sign-ins wait.</Note>}
        {s.sso === "configured" && (
          <dl className="kv">
            <Row k="provider" v={s.provider_host ?? "—"} />
            <Row k="client id" v={s.client_id ?? "—"} />
            {v && <>
              <Row k="issuer" v={v.issuer ?? "—"} />
              <Row k="allowed email domains" v={v.allowed_domains.length ? v.allowed_domains.join(", ") : "none: nobody can sign in"} />
              <Row k="bootstrap admin key" v={v.bootstrap_key_enabled ? "enabled" : "disabled"} />
              <Row k="bootstrap admins" v={String(v.admin_count)} />
              <Row k="trusted proxies" v={String(v.proxy_hops)} />
            </>}
          </dl>
        )}
        {s.sso === "configured" && !v && (
          <p className="muted tiny" style={{ margin: 0 }}>The server's own settings are shown to a signed-in admin. <Link to="/team">Sign in on the Team page</Link>.</p>
        )}
        <details>
          <summary>How to set up SSO (Microsoft Entra ID)</summary>
          <ol className="small prose" style={{ marginTop: 8 }}>
            <li>In Entra, register an application: single tenant, public client (no secret), and add the optional <span className="mono">email</span> claim to the ID token.</li>
            <li>Add the redirect URIs <span className="mono">http://127.0.0.1/callback</span> (command line) and <span className="mono">http://127.0.0.1:47821/api/team/callback</span> (this dashboard).</li>
            <li>On the team server set <span className="mono">SEEN_OIDC_ISSUER</span> (https://login.microsoftonline.com/&lt;tenant id&gt;/v2.0), <span className="mono">SEEN_OIDC_CLIENT_ID</span>, <span className="mono">SEEN_OIDC_ALLOWED_DOMAINS</span> and <span className="mono">SEEN_TEAM_ADMINS</span>, then restart it.</li>
            <li>Set the team server URL above, then use <b>Sign in with SSO</b> on the Team page or run <span className="mono">seen team login</span>.</li>
          </ol>
          <p className="muted tiny" style={{ margin: 0 }}>These settings live on the server, not in this dashboard, on purpose: changing them changes who is trusted to sign in.</p>
        </details>
      </div>
    </Card>
  );
}
