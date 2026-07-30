# Private ClamAV scanner specification

This is a provisioning specification, not a deployed service.

## Version and image

Use the official ClamAV 1.4 LTS line. At the time of this plan, the current LTS
patch is 1.4.5 and its expected LTS support date is August 15, 2027. The
provisioning change must resolve the official image to an immutable digest, for
example:

`clamav/clamav:1.4.5_base@sha256:<verified-digest>`

Do not use `latest`, `stable`, `unstable`, a floating feature tag, or an
unrecorded digest. The digest, image source, scan date, and vulnerability review
become part of the control manifest. Re-pin through a reviewed change when a
security update is required.

ClamAV's official [Docker guidance](https://docs.clamav.net/manual/Installing/Docker.html)
recommends a persistent signature-database volume with the `_base` image and
notes that the scanner may need about 4 GB of memory. Its
[support matrix](https://docs.clamav.net/faq/faq-eol.html) identifies 1.4 as the
current LTS line.

## Render boundary

- Deploy as a private service with no public URL in the same Render environment
  and region as the private API and worker.
- Address it only by a Render-private single-label service name such as
  `clamav-scanner:3310`. Code rejects URLs, IP literals, dotted/public hosts,
  invalid ports, and alternate endpoints.
- Give the scanner no object-store, database, Clerk, or audit credentials.
- The caller streams only a previously quarantined, size-bounded object using
  clamd `INSTREAM`. It never sends a filesystem path or signed URL.
- Permit scanner egress only for the documented FreshClam signature-update
  path. The assessment worker remains no-egress.
- Persist `/var/lib/clamav`; record the last successful update and reject
  definitions older than 24 hours.
- Apply a memory plan consistent with the official guidance and explicit CPU,
  request-time, and restart limits.

## Protocol and limits

Use newline-framed `nINSTREAM\n`, 4-byte big-endian chunk lengths, and a final
zero-length chunk. ClamAV documents this framing in its
[clamd protocol](https://docs.clamav.net/manual/Usage/ClamdProtocol.html).

Set clamd limits at least as strict as the application:

- `StreamMaxLength`: 25 MiB
- maximum accepted application object: 25 MiB
- caller timeout: no more than 120 seconds
- application chunk: no more than 1 MiB
- structural expanded-stream limit after a clean scan: 250 MiB
- page limit after a clean scan: 200
- PDF stream count after a clean scan: 10,000

The private client requires one complete newline-terminated response. Only the
exact single-line payload `<target>: OK` is clean. A nonempty
`<signature> FOUND` result is rejected. Empty, incomplete, oversized,
multiline, malformed, non-ASCII, error, timeout, unavailable, or ambiguous
responses are indeterminate and therefore rejected.

## Required negative tests

- EICAR is rejected and the audit reason is the generic `malware_detected`; the
  signature string is not returned to the browser.
- Scanner connection refused, timeout, restart, and empty/malformed response
  are indeterminate.
- Signature database older than 24 hours and implausibly future-dated metadata
  are rejected.
- 25 MiB plus one byte is rejected before or during streaming.
- A clean response without engine and signature-database identity is ineligible.
- No parser runs in any of those cases.
