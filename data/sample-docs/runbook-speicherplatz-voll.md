# Runbook: Speicherplatz voll

Verantwortlich: SRE · Gilt für: Docker-Hosts, Kubernetes-Knoten und persistente Volumes ·
Zuletzt geprüft: 2026-10

## Symptome

- Container starten nicht mehr, Logs melden `no space left on device`.
- Postgres wechselt in den Nur-Lese-Modus oder stürzt beim Schreiben des WAL ab.
- Qdrant lehnt Upserts ab; Uploads bleiben im Status `failed` hängen.

## Ursache finden

```bash
df -h                                   # welches Dateisystem ist voll?
df -i                                   # Inodes können auch ausgehen
sudo du -xh --max-depth=1 /var | sort -h | tail
docker system df                        # Images, Container, Volumes, Build-Cache
```

## Schnelle Entlastung

1. Ungenutzte Docker-Daten entfernen: `docker image prune -a` und `docker builder prune`.
   **Niemals** `docker volume prune` auf einem Host mit Datenbank-Volumes ausführen — das löscht Daten.
2. Alte Logdateien komprimieren oder löschen; danach Log-Rotation prüfen (`max-size` und `max-file`
   im Logging-Treiber von Docker).
3. Alte Qdrant-Snapshots im Snapshot-Verzeichnis löschen, wenn sie bereits extern gesichert sind.
4. Bei Postgres zuerst prüfen, ob ein Replikations-Slot oder ein fehlerhaftes WAL-Archiv das Löschen von
   WAL-Dateien verhindert: `select slot_name, active from pg_replication_slots;`

## Dauerhafte Lösung

- Alarm bei **80 % Belegung** einrichten, kritisch bei 90 %.
- Volumes vergrößern statt regelmäßig aufzuräumen; in Kubernetes eine StorageClass mit
  `allowVolumeExpansion: true` verwenden.
- Ein Vorfall durch vollen Speicher ist ein Zeichen für fehlendes Monitoring — im Postmortem festhalten.
