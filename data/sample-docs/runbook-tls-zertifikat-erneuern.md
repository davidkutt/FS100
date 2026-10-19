# Runbook: TLS-Zertifikat erneuern

Verantwortlich: Plattform-Team · Gilt für: alle öffentlich erreichbaren Endpunkte (Web, API, Keycloak) ·
Zuletzt geprüft: 2026-10

## Wann dieses Runbook gilt

Das Monitoring meldet **21 Tage vor Ablauf** eines Zertifikats eine Warnung und 7 Tage vorher einen
kritischen Alarm. Normalerweise erneuert cert-manager automatisch; dieses Runbook gilt, wenn die
automatische Erneuerung fehlgeschlagen ist oder ein Zertifikat manuell verwaltet wird.

## Ablaufdatum prüfen

```bash
echo | openssl s_client -connect api.example.org:443 -servername api.example.org 2>/dev/null \
  | openssl x509 -noout -enddate -subject -issuer
```

Wichtig ist `notAfter`. Prüfe auch, ob die vollständige Kette ausgeliefert wird — fehlende
Zwischenzertifikate fallen nur bei manchen Clients auf.

## Automatische Erneuerung mit cert-manager reparieren

1. Status ansehen: `kubectl describe certificate api-tls -n fs100` und die zugehörige `CertificateRequest`.
2. Häufigste Ursache ist eine fehlgeschlagene ACME-Challenge: DNS zeigt nicht auf den Ingress, oder die
   HTTP-01-Route wird von einer Weiterleitung blockiert.
3. Nach der Korrektur die Erneuerung anstoßen: `cmctl renew api-tls -n fs100`.
4. Warten, bis `Ready=True` gemeldet wird, dann das Ablaufdatum erneut prüfen.

## Manuelle Erneuerung

1. Neuen privaten Schlüssel und CSR erzeugen; den Schlüssel nie per Chat oder E-Mail weitergeben.
2. Zertifikat bei der CA beantragen und die vollständige Kette (Zertifikat + Zwischenzertifikate)
   herunterladen.
3. Als Kubernetes-Secret vom Typ `kubernetes.io/tls` einspielen und den Ingress neu laden.
4. Ablaufdatum und Kette wie oben prüfen; den Termin für die nächste Erneuerung im Kalender eintragen.

## Nach einem Ausfall durch ein abgelaufenes Zertifikat

Ein abgelaufenes Zertifikat ist mindestens ein SEV2-Vorfall. Im Postmortem klären, warum die Warnung
nach 21 Tagen nicht zu einer Erneuerung geführt hat.
