#!/usr/bin/env bash
# Token matrix of ADR-0009 against a Keycloak at $KEYCLOAK_URL (default: the throwaway on :8081).
set -uo pipefail
here=$(dirname "$0")
export KEYCLOAK_URL=${KEYCLOAK_URL:-http://localhost:8081}
T=$KEYCLOAK_URL/realms/kb/protocol/openid-connect/token
X=urn:ietf:params:oauth:grant-type:token-exchange
AT=urn:ietf:params:oauth:token-type:access_token
login="$here/../user-token/login.sh"
tok() { python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])'; }
for user in bob carol; do
  U=$("$login" "$user")
  echo "== $user, user token:"; echo "{\"access_token\":\"$U\"}" | python3 "$here/claims.py"
  H1=$(curl -s "$T" -d grant_type=$X -d client_id=kb-api -d client_secret=dev-only-change-me \
    -d subject_token="$U" -d subject_token_type=$AT -d audience=kb-ai)
  echo "hop 1 (kb-api, audience=kb-ai):"; echo "$H1" | python3 "$here/claims.py"
  echo "hop 2 (kb-ai, scope=kb:read kb:write):"
  curl -s "$T" -d grant_type=$X -d client_id=kb-ai -d client_secret=dev-only-change-me \
    -d subject_token="$(echo "$H1" | tok)" -d subject_token_type=$AT -d "scope=kb:read kb:write" | python3 "$here/claims.py"
done
echo "hop 2 on the raw user token (expect access_denied):"
curl -s "$T" -d grant_type=$X -d client_id=kb-ai -d client_secret=dev-only-change-me \
  -d subject_token="$U" -d subject_token_type=$AT -d scope=kb:read | python3 "$here/claims.py"
echo "kb-ai service account (expect aud=kb-api, client role ingest-on-behalf):"
curl -s "$T" -d grant_type=client_credentials -d client_id=kb-ai -d client_secret=dev-only-change-me | python3 "$here/claims.py"
