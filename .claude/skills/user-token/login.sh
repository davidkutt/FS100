#!/usr/bin/env bash
# Prints an access token for a realm-kb seed user via Authorization Code + PKCE (kb-web).
set -euo pipefail
user=$1
kc=http://localhost:8080/realms/kb/protocol/openid-connect
redirect=http://localhost:4200/
verifier=$(openssl rand -hex 48)
challenge=$(printf %s "$verifier" | openssl dgst -binary -sha256 | openssl base64 | tr '+/' '-_' | tr -d '=')
jar=$(mktemp)
page=$(curl -s -c "$jar" -b "$jar" "$kc/auth?client_id=kb-web&response_type=code&scope=openid&redirect_uri=$redirect&code_challenge=$challenge&code_challenge_method=S256")
action=$(printf %s "$page" | grep -o 'action="[^"]*"' | head -1 | sed 's/^action="//;s/"$//;s/&amp;/\&/g')
location=$(curl -s -c "$jar" -b "$jar" -o /dev/null -w '%{redirect_url}' --data-urlencode "username=$user" --data-urlencode "password=$user" "$action")
code=$(printf %s "$location" | sed -n 's/.*[?&]code=\([^&]*\).*/\1/p')
rm -f "$jar"
curl -s "$kc/token" -d grant_type=authorization_code -d client_id=kb-web -d "code=$code" -d "redirect_uri=$redirect" -d "code_verifier=$verifier" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
