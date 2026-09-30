# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately, through GitHub's
[private vulnerability reporting](https://github.com/ianderso/familysearch-mcp/security/advisories/new)
(the **Report a vulnerability** button on the repository's Security tab), not
in a public issue. Include what an attacker controls, what they gain, and the
steps to reproduce it.

You should hear back within a week. Fixes are released for the latest version
only.

## Scope

In scope: this server — how it handles the access token, the files it
writes, the requests it makes, and anything a tool argument or an API
response can make it do.

Out of scope: FamilySearch's own services, which this project does not
operate. Report problems with those to FamilySearch.

## The security model, briefly

- **The package never handles a password.** It takes an access token and
  sends it only to FamilySearch hosts over HTTPS: the API, the website's
  search service, and the image hosts. `download_image` refuses any other
  URL, and the download itself will not attach the token to one.
- **The token is read, never written.** It comes from the environment or
  the env file, and a refreshed one is re-read from that file after a 401.
  It is not logged, cached or included in a tool result. Request URLs are
  not logged either: they carry searched names and presigned image links.
- **The server writes to FamilySearch never, and to local disk twice.**
  `download_image` creates a new file at a path the model chooses, using
  exclusive creation, so it cannot overwrite or truncate an existing file.
  The name must end in an image or PDF suffix, so it cannot create a file
  the system acts on by its existence alone, such as a launch agent, a
  shell profile or an ssh `authorized_keys`. It is annotated as not
  read-only, so a client can require approval for it. The collection
  catalogue is cached under `~/.cache/familysearch-mcp/`.
- **Ids are checked before they reach a request path**, so a tool argument
  cannot redirect a request to another API route.
- **Responses carry untrusted text.** Names, memories, notes, source titles
  and change reasons in the shared tree are written by other FamilySearch
  users and reach the model verbatim, which makes them a channel for prompt
  injection. The server's instructions tell the model to treat that text as
  material, not as instructions, but the model still decides what to do
  next. An injection that leads the model to misuse this server's own tools
  is in scope; one that leads it to misuse other tools the client has
  connected is a client concern.
