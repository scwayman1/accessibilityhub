# syntax=docker/dockerfile:1
# Verified 2026-07-30 from the official Docker Hub manifest for
# clamav/clamav:1.4.5_base (linux/amd64, build 105).
FROM clamav/clamav:1.4.5_base@sha256:3e2eac6cdbd5c5cb408990e6fe02b81d91298bc71090e7f3bc2ab7f7a3a256f6

# Fail the build if the upstream configuration layout changes, then impose
# limits no weaker than the application intake policy. Concurrent reloads are
# disabled so the documented 4 GiB instance does not briefly require two
# signature engines; scans block during a database reload and therefore fail
# closed at the caller timeout.
RUN grep -Eq '^#?StreamMaxLength ' /etc/clamav/clamd.conf \
    && grep -Eq '^#?MaxFileSize ' /etc/clamav/clamd.conf \
    && grep -Eq '^#?MaxScanSize ' /etc/clamav/clamd.conf \
    && grep -Eq '^#?ConcurrentDatabaseReload ' /etc/clamav/clamd.conf \
    && sed -i \
        -e 's/^#*StreamMaxLength .*/StreamMaxLength 25M/' \
        -e 's/^#*MaxFileSize .*/MaxFileSize 25M/' \
        -e 's/^#*MaxScanSize .*/MaxScanSize 250M/' \
        -e 's/^#*ConcurrentDatabaseReload .*/ConcurrentDatabaseReload no/' \
        /etc/clamav/clamd.conf
