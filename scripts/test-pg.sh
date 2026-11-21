#!/usr/bin/env bash
# Geçici Postgres kapsayıcısı (tmpfs, yalnız 127.0.0.1, rastgele port) ile PG'ye bağlı testleri koşar; bitince kapsayıcı SİLİNİR.
# claudeops'un kendi test kapsayıcısı: varaka'nın ya da canlı hiçbir DB'ye dokunmaz.
# Kullanım: scripts/test-pg.sh [unittest modülleri...]      (varsayılan: test_dbapi test_store_pg)
#   PG_IMAGE (varsayılan postgres:16-alpine; yerelde olmalı, çekmez)
set -euo pipefail
IMG="${PG_IMAGE:-postgres:16-alpine}"
NAME="claudeops-testpg-$$"
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
docker run -d --rm --name "$NAME" -e POSTGRES_PASSWORD=t -e POSTGRES_DB=t --tmpfs /var/lib/postgresql/data \
  -p "127.0.0.1:$PORT:5432" "$IMG" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$NAME" pg_isready -U postgres -d t >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$NAME" pg_isready -U postgres -d t >/dev/null
sleep 1
export CLAUDEOPS_TEST_PG_URL="postgresql://postgres:t@127.0.0.1:$PORT/t"
cd "$REPO/py/tests"
mods=("$@"); [ ${#mods[@]} -gt 0 ] || mods=(test_dbapi)
python3 -m unittest "${mods[@]}"
