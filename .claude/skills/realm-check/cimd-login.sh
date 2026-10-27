#!/usr/bin/env bash
# Logs a seed user in the way an MCP client with a Client ID Metadata Document does (PKCE S256, `resource`,
# consent screen) and prints the token response. Keycloak fetches the real document from the client's host.
# Usage: cimd-login.sh <user> [client_id] [redirect_uri] [scope] [resource]   (empty scope/resource = omit)
set -euo pipefail
user=$1
cid=${2:-https://claude.ai/oauth/claude-code-client-metadata}
redirect=${3:-http://localhost:54321/callback}
scope=${4-kb:read offline_access}  # what Claude Code asks for
resource=${5-http://localhost:8000/mcp}
base=${KEYCLOAK_URL:-http://localhost:8081}
kc=$base/realms/kb/protocol/openid-connect
verifier=$(openssl rand -hex 48)
challenge=$(printf %s "$verifier" | openssl dgst -binary -sha256 | openssl base64 | tr '+/' '-_' | tr -d '=')
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT
form_action() { grep -o 'action="[^"]*"' | head -1 | sed 's/^action="//;s/"$//;s/&amp;/\&/g'; }

q=(--data-urlencode "client_id=$cid" -d response_type=code --data-urlencode "redirect_uri=$redirect"
  -d "code_challenge=$challenge" -d code_challenge_method=S256 -d state=s)
[ -n "$scope" ] && q+=(--data-urlencode "scope=$scope")
[ -n "$resource" ] && q+=(--data-urlencode "resource=$resource")
page=$(curl -s -G -c "$jar" -b "$jar" -w '\n%{http_code} %{redirect_url}' "${q[@]}" "$kc/auth")
action=$(printf %s "$page" | form_action || true)
[ -n "$action" ] || { echo "authorize refused: $(printf %s "$page" | tail -1)" >&2; exit 1; }
location=$(curl -s -c "$jar" -b "$jar" -o /dev/null -w '%{redirect_url}' \
  --data-urlencode "username=$user" --data-urlencode "password=$user" "$action")
if [[ $location != *code=* ]]; then # consent screen, once per user and client
  grant=$(curl -s -c "$jar" -b "$jar" "$location")
  location=$(curl -s -c "$jar" -b "$jar" -o /dev/null -w '%{redirect_url}' -d accept=Yes \
    --data-urlencode "code=$(printf %s "$grant" | sed -n 's/.*name="code" value="\([^"]*\)".*/\1/p')" \
    "$base$(printf %s "$grant" | form_action)")
fi
code=$(printf %s "$location" | sed -n 's/.*[?&]code=\([^&]*\).*/\1/p')
[ -n "$code" ] || { echo "no code: $location" >&2; exit 1; }
t=(-d grant_type=authorization_code --data-urlencode "client_id=$cid" -d "code=$code"
  --data-urlencode "redirect_uri=$redirect" -d "code_verifier=$verifier")
[ -n "$resource" ] && t+=(--data-urlencode "resource=$resource")
curl -s "$kc/token" "${t[@]}"
