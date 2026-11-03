# Configure Keycloak login

Use this guide with [Deploy RTMF](DEPLOYMENT.md). Keycloak supplies
user login and application permissions. There is no built-in RTMF admin
account or default password.

To install a new server and its persistent database, follow
[Keycloak server setup](INFRASTRUCTURE.md#keycloak-server) first.

For the examples below, replace `https://rtmf.example` with the public
frontend address and `https://identity.example` with your Keycloak address.
RTMF containers must be able to reach the realm URL and trust its HTTPS
certificate. See the [Keycloak administration guide](https://www.keycloak.org/docs/latest/server_admin/index.html)
for the corresponding Admin Console screens.

## 1. Create the realm and login client

Create a realm named `rtmf`. Its issuer URL is:

```text
https://identity.example/realms/rtmf
```

In that realm, create an OpenID Connect client with these settings:

| Setting | Value |
| --- | --- |
| Client ID | `rtmf-web` |
| Client authentication | On |
| Standard flow | On |
| Implicit flow | Off |
| Direct access grants | Off |
| Service accounts | Off |
| PKCE method | `S256` |
| Valid redirect URI | `https://rtmf.example/auth/callback` |

Copy the client's secret from its Credentials screen. Use the exact callback
URI; it must match the manifest. The browser talks to RTMF, which performs
the authorization-code exchange with Keycloak on the server.

## 2. Create application roles and the audience mapper

Create a second OpenID Connect client named `rtmf-use-case` for application
permissions. It does not perform browser login; disable its authentication
flows. Under its Roles tab, create these client roles:

```text
system.read
simulator.read
simulator.write
job.read
job.create
simulation.read
system_discovery.training.read
system_discovery.training.write
system_discovery.model.read
system_discovery.model.write
system_discovery.simulation.read
system_discovery.simulation.write
```

For `rtmf-web`, keep the built-in `roles` client scope assigned as a default
scope so client roles appear in access tokens. If Full Scope Allowed is off,
explicitly include the `rtmf-use-case` client roles in its role scope mappings.

Open the login client's dedicated client scope under Client scopes, then
Mappers → Configure a new mapper → Audience. Set Included Client Audience to
`rtmf-use-case` and Add to access token to On. Save the mapper.

An issued access token must include:

```text
resource_access.rtmf-use-case.roles
```

Its `aud` claim must contain `rtmf-use-case`. The manifest defaults for
`permissions_client_id` and `expected_access_token_audience` use that value.

## 3. Create the first user

Create a user in the `rtmf` realm and set a password. Assign the client roles
needed for that person's workflows. For an operator verifying the complete
installation, assign the roles listed above; use narrower role sets for other
users. A successful Keycloak login without the required roles can still produce
an empty navigation menu or HTTP `403` in RTMF.

## 4. Configure RTMF

In `config/deployment.json`, set:

```text
runtime.services.front.authentication.callback_url
runtime.services.use_case.authentication.keycloak.issuer_url
runtime.services.use_case.authentication.keycloak.client_id
```

Use the URLs and client ID from step 1. In the prepared directory's `.env`, set
`RTMF_KEYCLOAK_CLIENT_SECRET` to the client's secret. Generate
`RTMF_KEYCLOAK_TOKEN_ENCRYPTION_KEY` and `RTMF_SESSION_TOKEN_PEPPER` using the
commands in [Deployment](DEPLOYMENT.md#3-fill-credentials).

## 5. Verify login

Render and start the application, open its public HTTPS URL, and sign in. The
browser should return through `/auth/callback` and show the navigation allowed
by the user's roles. Logout uses `POST /auth/logout`. The application keeps
sessions in memory; restarting front signs users out. Keycloak tokens are held
server-side rather than in browser storage.

## Source development over HTTP

Use `config/rtmf.local.example.json` as the starting point. It already uses
a non-prefixed cookie name, disables secure cookies for local development, and
allows an HTTP Keycloak issuer. Set the source template's Keycloak variables
(`KEYCLOAK_HOST`, `KEYCLOAK_PORT`, `RTMF_KEYCLOAK_CLIENT_ID`) plus the secret
variables above. Register the exact redirect URI
`http://localhost:5000/auth/callback`. Keep the public deployment's HTTPS cookie
settings when deploying the production manifest.
