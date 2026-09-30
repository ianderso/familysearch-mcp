# Authentication

This package ships **no client id** and never handles a FamilySearch password.
To reach the authenticated tools you supply an access token from your own
registered application.

## Why it works this way

A FamilySearch production credential is issued to an *application*, not to a
piece of software someone downloaded. Two shortcuts exist and the package
takes neither:

- **Borrowing another project's published client id.** It works, and it is
  someone else's credential. Volume against it can get that id rate-limited or
  revoked, breaking every user of the project it belongs to.
- **Posting a username and password to the sign-in form.** That means asking
  users to hand their FamilySearch password to a third-party tool, and it
  breaks whenever the sign-in flow changes.

The cost is that authenticated tools need setup. The benefit is that nothing
here depends on a credential that can disappear, and no password passes
through it.

## Getting a client id

Register at [FamilySearch for Developers](https://www.familysearch.org/developers/).

An individual developer key reaches only the **Integration sandbox**, which
holds synthetic data. Production keys go through FamilySearch's solution
provider programme, which accepts only a registered business or nonprofit
and requires a compatibility review.

Set `FS_ENVIRONMENT=integration` to work against the sandbox.

## Getting a token

Run your application's OAuth authorization-code flow and put the resulting
bearer token in `FS_ACCESS_TOKEN`, preferably in the env file `FS_ENV_FILE`
names. The server sends it as-is and never refreshes it itself, but when it
expires the server re-reads the file, so a token refreshed there is picked
up mid-session. See [When a token expires mid-session](#when-a-token-expires-mid-session).

`auth_status` reports what is configured and what is missing. With a token
configured, it also asks FamilySearch whether that token is still accepted
(`token_accepted`). `authenticated` only means one is set.

## What works without credentials

FamilySearch serves its catalogues anonymously: places, record collections,
their field dictionaries, and the waypoint tree that browses a film. So these
work with no setup at all:

- the gazetteer: `search_places`, `search_places_at_date`, `get_place`,
  `get_place_jurisdictions`, `get_place_children`;
- the collection catalogue: `search_collections`, `get_collection`,
  `get_collection_fields`, `browse_waypoints`;
- the navigation half of the image tools: `get_image_links` returns the
  neighbouring pages and the records link without a token, and
  `get_film_image` checks that a film and image number exist;
- `auth_status`, since its job is to report what is missing.

The boundary is data about people. Records, personas, the page images
themselves and the tree all need a token.

The client keeps the list of anonymous paths explicitly, and refuses locally
for anything else rather than sending a request with no credential and
letting the server produce a confusing 401.

## Verified anonymous access

Confirmed against production on 2026-09-23, with no `Authorization` header
and no client id in the environment:

| Route | Result |
| --- | --- |
| `GET /platform/places/search` | 200 — but **406** if you send `application/x-gedcomx-v1+json`. It is a feed and wants `application/x-gedcomx-atom+json`. |
| `GET /platform/places/description/{id}` | 200 |
| `GET /platform/records/collections` | 200 |
| `GET /platform/tree/persons/{id}` | refused locally by this server before a request is sent |

Running the tools themselves with an empty environment returned real places
for a town name and resolved place 442 to "Alta California, Mexico" —
a province, with the dates its jurisdiction existed. That is the historical
jurisdiction resolution this server exists to make available without setup.

The record collections route answers anonymously too, and
`/platform/records/collections/{id}` carries the label dictionary that turns
a field code such as `PR_FTHR_NAME` into "Father's Name". That is what
`get_collection_fields` reads. [API-NOTES.md](API-NOTES.md) lists every
route checked.

## When a token expires mid-session

A server process reads its environment once at startup. A token lasts about
an hour. So any session longer than that outlives its credential, and the
symptom is unhelpful: the host sees the process as healthy and will not
reconnect it, while every call returns 401.

The server recovers on its own. On a 401 it re-reads `FS_ACCESS_TOKEN` from
the env file and retries once, so **refreshing the file is enough** — no
reconnect, no new session. `auth_status` reports which file it will read.

It reads the **file**, not the environment: `load_dotenv` does not override
a variable already set in the process, which is precisely the case when a
launcher exports the token before starting the server.

Two boundaries on that retry. It happens once, so a genuinely dead token
still surfaces rather than looping. And it only adopts a token someone else
obtained — it never signs in, so the guarantee that this server does not
handle your password is unaffected.

The server finds the file the same way at startup and on a 401: `FS_ENV_FILE`
if set, otherwise the nearest `.env` from its working directory upward.
`auth_status` reports `token_source: "environment only"` when neither finds
one, and then recovery is off. An expired token will need a restart.

**Set `FS_ENV_FILE` whenever the launcher exports the token.** That covers a
wrapper that does `set -a; . ~/project/.env` before starting the server, and a
client config that passes `FS_ACCESS_TOKEN` in its `env` block. The server
sees the value but cannot tell which file it came from. `FS_ENV_FILE` alone
is also enough: the server loads the token from it at startup, so nothing
needs exporting.

## Keeping a token live

FamilySearch's token endpoint returns `access_token`, `id_token` and
`token_type` — **no refresh token, and no stated expiry.** Verified live on
2026-09-23. So there is no way to extend a session: keeping a token live
means running your application's sign-in again, roughly every hour.

The server stays out of that. Whatever obtains the next token only has to
write it to the env file as `FS_ACCESS_TOKEN=...`, and the running server
picks it up on its next call. Keep that file readable by you alone
(`chmod 600`): it holds a bearer credential.
