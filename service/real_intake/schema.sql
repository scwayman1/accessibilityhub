-- PostgreSQL foundation for owner-scoped real-intake records.
-- This file is not used by the public synthetic SQLite repository.
-- Apply only through a reviewed migration after private Render Postgres exists.

BEGIN;

CREATE TABLE IF NOT EXISTS real_documents (
    id UUID PRIMARY KEY,
    owner_clerk_user_id TEXT NOT NULL
        CHECK (owner_clerk_user_id ~ '^user_[A-Za-z0-9_-]{8,128}$'),
    original_filename TEXT NOT NULL CHECK (
        length(original_filename) BETWEEN 1 AND 200
        AND original_filename = btrim(original_filename)
        AND original_filename !~ '[/\\]'
        AND original_filename !~ '[[:cntrl:]]'
        AND lower(original_filename) LIKE '%.pdf'
    ),
    source_kind TEXT NOT NULL CHECK (source_kind = 'controlled_real_upload'),
    state TEXT NOT NULL CHECK (
        state IN (
            'quarantined', 'rejected', 'clean', 'queued', 'processing',
            'ready', 'deletion_pending'
        )
    ),
    sha256 CHAR(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    object_size BIGINT NOT NULL CHECK (
        object_size BETWEEN 1 AND 26214400
    ),
    quarantine_key TEXT NOT NULL UNIQUE,
    clean_key TEXT UNIQUE,
    derivative_prefix TEXT UNIQUE,
    evidence_prefix TEXT UNIQUE,
    scan_verdict TEXT CHECK (scan_verdict IN ('clean', 'rejected', 'indeterminate')),
    scan_engine_version TEXT,
    scan_signature_database_version TEXT,
    scan_definitions_age_seconds INTEGER
        CHECK (scan_definitions_age_seconds IS NULL OR scan_definitions_age_seconds >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, owner_clerk_user_id),
    CHECK (
        quarantine_key =
        'quarantine/' || owner_clerk_user_id || '/' || id::text || '.pdf'
    ),
    CHECK (
        clean_key IS NULL OR clean_key =
        'clean/' || owner_clerk_user_id || '/' || id::text || '.pdf'
    ),
    CHECK (
        derivative_prefix IS NULL OR derivative_prefix =
        'derivative/' || owner_clerk_user_id || '/' || id::text || '/'
    ),
    CHECK (
        evidence_prefix IS NULL OR evidence_prefix =
        'evidence/' || owner_clerk_user_id || '/' || id::text || '/'
    ),
    CHECK (
        clean_key IS NULL OR scan_verdict = 'clean'
    ),
    CHECK (
        state NOT IN ('clean', 'queued', 'processing', 'ready')
        OR clean_key IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS real_processing_jobs (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL,
    owner_clerk_user_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('queued', 'running', 'succeeded', 'failed', 'canceled')
    ),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    FOREIGN KEY (document_id, owner_clerk_user_id)
        REFERENCES real_documents(id, owner_clerk_user_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS real_upload_authorizations (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL,
    owner_clerk_user_id TEXT NOT NULL,
    quarantine_key TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL CHECK (content_type = 'application/pdf'),
    max_bytes BIGINT NOT NULL CHECK (max_bytes BETWEEN 1 AND 26214400),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    FOREIGN KEY (document_id, owner_clerk_user_id)
        REFERENCES real_documents(id, owner_clerk_user_id)
        ON DELETE CASCADE,
    CHECK (
        quarantine_key =
        'quarantine/' || owner_clerk_user_id || '/' ||
        document_id::text || '.pdf'
    ),
    CHECK (expires_at > created_at),
    CHECK (expires_at <= created_at + INTERVAL '5 minutes'),
    CHECK (consumed_at IS NULL OR consumed_at >= created_at)
);

CREATE OR REPLACE FUNCTION consume_real_upload_authorization(
    p_id UUID,
    p_owner_clerk_user_id TEXT,
    p_quarantine_key TEXT,
    p_content_type TEXT,
    p_object_size BIGINT,
    p_consumed_at TIMESTAMPTZ
)
RETURNS SETOF real_upload_authorizations
LANGUAGE sql
SECURITY INVOKER
AS $$
    UPDATE real_upload_authorizations
       SET consumed_at = p_consumed_at
     WHERE id = p_id
       AND owner_clerk_user_id = p_owner_clerk_user_id
       AND quarantine_key = p_quarantine_key
       AND content_type = p_content_type
       AND p_object_size BETWEEN 1 AND max_bytes
       AND consumed_at IS NULL
       AND p_consumed_at BETWEEN created_at AND expires_at
    RETURNING *;
$$;

CREATE TABLE IF NOT EXISTS real_findings (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL,
    owner_clerk_user_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (
        lane IN (
            'needs_attention', 'review_recommended',
            'verified_signal', 'not_assessed'
        )
    ),
    evidence_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id, owner_clerk_user_id)
        REFERENCES real_documents(id, owner_clerk_user_id)
        ON DELETE CASCADE,
    CHECK (
        evidence_key IS NULL OR evidence_key LIKE (
            'evidence/' || owner_clerk_user_id || '/' ||
            document_id::text || '/%'
        )
    )
);

CREATE TABLE IF NOT EXISTS real_deletion_requests (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL,
    owner_clerk_user_id TEXT NOT NULL,
    requested_by_clerk_user_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('requested', 'running', 'verified', 'failed')
    ),
    verification_id TEXT,
    objects_deleted INTEGER CHECK (objects_deleted IS NULL OR objects_deleted >= 0),
    records_deleted INTEGER CHECK (records_deleted IS NULL OR records_deleted >= 0),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    -- Deliberately no document foreign key: a verified deletion request and its
    -- target UUID must survive removal of the document metadata row.
    CHECK (owner_clerk_user_id ~ '^user_[A-Za-z0-9_-]{8,128}$'),
    CHECK (requested_by_clerk_user_id = owner_clerk_user_id)
);

CREATE TABLE IF NOT EXISTS real_model_egress_consents (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL,
    owner_clerk_user_id TEXT NOT NULL,
    granted_by_clerk_user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    purpose TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMPTZ,
    FOREIGN KEY (document_id, owner_clerk_user_id)
        REFERENCES real_documents(id, owner_clerk_user_id)
        ON DELETE CASCADE,
    CHECK (owner_clerk_user_id ~ '^user_[A-Za-z0-9_-]{8,128}$'),
    CHECK (granted_by_clerk_user_id = owner_clerk_user_id)
);

CREATE OR REPLACE FUNCTION real_audit_detail_is_safe(
    p_action TEXT,
    p_detail JSONB
)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT
        jsonb_typeof(p_detail) = 'object'
        AND octet_length(p_detail::text) <= 4096
        AND (
            p_detail - (
                CASE p_action
                    WHEN 'upload_authorization_created' THEN
                        ARRAY['authorization_id', 'max_bytes', 'expires_at']
                    WHEN 'upload_received' THEN
                        ARRAY['object_size', 'sha256', 'source_kind']
                    WHEN 'validation_completed' THEN
                        ARRAY[
                            'outcome', 'reason_code', 'page_count',
                            'stream_count'
                        ]
                    WHEN 'scan_completed' THEN
                        ARRAY[
                            'outcome', 'reason_code', 'engine_version',
                            'signature_database_version',
                            'definitions_age_seconds'
                        ]
                    WHEN 'processing_queued' THEN ARRAY['job_id']
                    WHEN 'processing_started' THEN ARRAY['job_id', 'attempt']
                    WHEN 'processing_succeeded' THEN
                        ARRAY['job_id', 'finding_count']
                    WHEN 'processing_failed' THEN ARRAY['job_id', 'error_code']
                    WHEN 'document_viewed' THEN ARRAY[]::TEXT[]
                    WHEN 'document_downloaded' THEN ARRAY['derivative_kind']
                    WHEN 'deletion_requested' THEN ARRAY['deletion_request_id']
                    WHEN 'deletion_completed' THEN
                        ARRAY[
                            'deletion_request_id', 'objects_deleted',
                            'records_deleted', 'verification_id'
                        ]
                    WHEN 'deletion_failed' THEN
                        ARRAY['deletion_request_id', 'error_code']
                    WHEN 'model_egress_consented' THEN
                        ARRAY['consent_id', 'provider', 'purpose']
                    WHEN 'model_egress_used' THEN
                        ARRAY[
                            'consent_id', 'provider', 'purpose', 'request_id'
                        ]
                    ELSE ARRAY[]::TEXT[]
                END
            )
        ) = '{}'::JSONB
        AND NOT EXISTS (
            SELECT 1
              FROM jsonb_each(p_detail) AS item(field_name, field_value)
             WHERE jsonb_typeof(field_value) NOT IN (
                       'string', 'number', 'boolean', 'null'
                   )
                OR octet_length(field_value::text) > 512
                OR lower(field_value::text) ~ '^"https?://'
        );
$$;

CREATE TABLE IF NOT EXISTS real_audit_events (
    sequence_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    owner_clerk_user_id TEXT NOT NULL,
    actor_clerk_user_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (
        action IN (
            'upload_authorization_created', 'upload_received',
            'validation_completed', 'scan_completed', 'processing_queued',
            'processing_started', 'processing_succeeded', 'processing_failed',
            'document_viewed', 'document_downloaded', 'deletion_requested',
            'deletion_completed', 'deletion_failed',
            'model_egress_consented', 'model_egress_used'
        )
    ),
    target_id UUID,
    request_id TEXT NOT NULL CHECK (length(request_id) BETWEEN 1 AND 128),
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (owner_clerk_user_id ~ '^user_[A-Za-z0-9_-]{8,128}$'),
    CHECK (actor_clerk_user_id = owner_clerk_user_id),
    CHECK (real_audit_detail_is_safe(action, detail))
);

CREATE OR REPLACE FUNCTION reject_real_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'real_audit_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS real_audit_events_append_only ON real_audit_events;
CREATE TRIGGER real_audit_events_append_only
BEFORE UPDATE OR DELETE ON real_audit_events
FOR EACH ROW EXECUTE FUNCTION reject_real_audit_mutation();

CREATE INDEX IF NOT EXISTS real_documents_owner_created
    ON real_documents(owner_clerk_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS real_processing_jobs_owner_state_created
    ON real_processing_jobs(owner_clerk_user_id, state, created_at);
CREATE INDEX IF NOT EXISTS real_upload_authorizations_owner_expiry
    ON real_upload_authorizations(owner_clerk_user_id, expires_at);
CREATE INDEX IF NOT EXISTS real_deletion_requests_owner_state
    ON real_deletion_requests(owner_clerk_user_id, state, requested_at);
CREATE INDEX IF NOT EXISTS real_findings_owner_document
    ON real_findings(owner_clerk_user_id, document_id);
CREATE INDEX IF NOT EXISTS real_audit_events_owner_sequence
    ON real_audit_events(owner_clerk_user_id, sequence_id);

-- Each API transaction must SET LOCAL hub.owner_clerk_user_id to the verified
-- Clerk subject before accessing these tables. A missing setting yields no rows.
ALTER TABLE real_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE real_documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS real_documents_owner_policy ON real_documents;
CREATE POLICY real_documents_owner_policy ON real_documents
    USING (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    )
    WITH CHECK (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    );

ALTER TABLE real_processing_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE real_processing_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS real_processing_jobs_owner_policy
    ON real_processing_jobs;
CREATE POLICY real_processing_jobs_owner_policy ON real_processing_jobs
    USING (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    )
    WITH CHECK (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    );

ALTER TABLE real_upload_authorizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE real_upload_authorizations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS real_upload_authorizations_owner_policy
    ON real_upload_authorizations;
CREATE POLICY real_upload_authorizations_owner_policy
    ON real_upload_authorizations
    USING (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    )
    WITH CHECK (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    );

ALTER TABLE real_deletion_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE real_deletion_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS real_deletion_requests_owner_policy
    ON real_deletion_requests;
CREATE POLICY real_deletion_requests_owner_policy ON real_deletion_requests
    USING (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    )
    WITH CHECK (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    );

ALTER TABLE real_findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE real_findings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS real_findings_owner_policy ON real_findings;
CREATE POLICY real_findings_owner_policy ON real_findings
    USING (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    )
    WITH CHECK (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    );

ALTER TABLE real_model_egress_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE real_model_egress_consents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS real_model_egress_consents_owner_policy
    ON real_model_egress_consents;
CREATE POLICY real_model_egress_consents_owner_policy
    ON real_model_egress_consents
    USING (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    )
    WITH CHECK (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    );

ALTER TABLE real_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE real_audit_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS real_audit_events_owner_policy ON real_audit_events;
CREATE POLICY real_audit_events_owner_policy ON real_audit_events
    FOR SELECT
    USING (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
    );
DROP POLICY IF EXISTS real_audit_events_insert_policy ON real_audit_events;
CREATE POLICY real_audit_events_insert_policy ON real_audit_events
    FOR INSERT
    WITH CHECK (
        owner_clerk_user_id =
        current_setting('hub.owner_clerk_user_id', true)
        AND actor_clerk_user_id = owner_clerk_user_id
    );

COMMIT;
