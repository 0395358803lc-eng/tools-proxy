# Security

## Local secrets

SOCKS5 credentials must never be committed to Git. Runtime credentials are stored in
`proxies.local.json`, which is ignored by Git. `config.local.json` is also ignored and may
contain machine-specific configuration.

The bridge receives only a proxy identifier and the path to the local secret store. Passwords
are not embedded in source code and are not passed as command-line arguments.

## Network exposure

The HTTP bridge listens on `127.0.0.1` by default. Do not change `bridge_bind_host` to
`0.0.0.0` unless you also understand and restrict the Windows Firewall exposure.

## Previously exposed credentials

If a previous repository revision contained real proxy credentials, removing them from the
current branch does not invalidate credentials already present in Git history. Rotate those
credentials at the proxy provider. If history removal is required, perform a coordinated
history rewrite after all collaborators are informed.
