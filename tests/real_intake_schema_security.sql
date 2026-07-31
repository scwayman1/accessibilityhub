\set ON_ERROR_STOP on

BEGIN;

CREATE ROLE hub_real_intake_test NOLOGIN;
GRANT USAGE ON SCHEMA public TO hub_real_intake_test;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO hub_real_intake_test;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
    TO hub_real_intake_test;
GRANT EXECUTE ON FUNCTION consume_real_upload_authorization(
    UUID, TEXT, TEXT, TEXT, BIGINT, TIMESTAMPTZ
) TO hub_real_intake_test;

SET ROLE hub_real_intake_test;
SELECT set_config(
    'hub.owner_clerk_user_id',
    'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
    true
);

INSERT INTO real_documents (
    id, owner_clerk_user_id, original_filename, source_kind, state, sha256,
    object_size, quarantine_key
) VALUES (
    'c2b21f86-66f7-43f5-94a4-4c5f9f9c35af',
    'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
    'test.pdf',
    'controlled_real_upload',
    'quarantined',
    repeat('a', 64),
    1024,
    'quarantine/user_2RfWKJREkjKbHZy0Wqa5qrHeAnb/c2b21f86-66f7-43f5-94a4-4c5f9f9c35af.pdf'
);

INSERT INTO real_upload_authorizations (
    id, document_id, owner_clerk_user_id, quarantine_key, content_type,
    max_bytes, created_at, expires_at
) VALUES (
    '90111f60-5614-4b48-8407-44893c75fc3c',
    'c2b21f86-66f7-43f5-94a4-4c5f9f9c35af',
    'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
    'quarantine/user_2RfWKJREkjKbHZy0Wqa5qrHeAnb/c2b21f86-66f7-43f5-94a4-4c5f9f9c35af.pdf',
    'application/pdf',
    26214400,
    '2026-07-30T20:00:00Z',
    '2026-07-30T20:05:00Z'
);

DO $$
DECLARE
    consumed_count INTEGER;
BEGIN
    SELECT count(*) INTO consumed_count
      FROM consume_real_upload_authorization(
        '90111f60-5614-4b48-8407-44893c75fc3c',
        'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
        'quarantine/user_2RfWKJREkjKbHZy0Wqa5qrHeAnb/c2b21f86-66f7-43f5-94a4-4c5f9f9c35af.pdf',
        'application/pdf',
        1024,
        '2026-07-30T20:01:00Z'
      );
    IF consumed_count <> 1 THEN
        RAISE EXCEPTION 'first upload authorization consumption must succeed once';
    END IF;

    SELECT count(*) INTO consumed_count
      FROM consume_real_upload_authorization(
        '90111f60-5614-4b48-8407-44893c75fc3c',
        'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
        'quarantine/user_2RfWKJREkjKbHZy0Wqa5qrHeAnb/c2b21f86-66f7-43f5-94a4-4c5f9f9c35af.pdf',
        'application/pdf',
        1024,
        '2026-07-30T20:02:00Z'
      );
    IF consumed_count <> 0 THEN
        RAISE EXCEPTION 'upload authorization reuse must fail';
    END IF;
END;
$$;

INSERT INTO real_audit_events (
    id, owner_clerk_user_id, actor_clerk_user_id, action, target_id,
    request_id, detail
) VALUES (
    '8fd4b65c-4e64-4a07-88d7-bfa4374b088a',
    'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
    'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
    'upload_received',
    'c2b21f86-66f7-43f5-94a4-4c5f9f9c35af',
    'request-id',
    '{"object_size": 1024}'::jsonb
);

INSERT INTO real_deletion_requests (
    id, document_id, owner_clerk_user_id, requested_by_clerk_user_id, state
) VALUES (
    '2f19b85b-e201-45b0-bbb1-c7278f3ec790',
    'c2b21f86-66f7-43f5-94a4-4c5f9f9c35af',
    'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
    'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
    'requested'
);

DO $$
BEGIN
    UPDATE real_deletion_requests
       SET state = 'running'
     WHERE id = '2f19b85b-e201-45b0-bbb1-c7278f3ec790';
    UPDATE real_deletion_requests
       SET state = 'verified',
           verification_id = 'test-deletion-verification',
           objects_deleted = 1,
           records_deleted = 4,
           finished_at = CURRENT_TIMESTAMP
     WHERE id = '2f19b85b-e201-45b0-bbb1-c7278f3ec790';
    BEGIN
        DELETE FROM real_deletion_requests
         WHERE id = '2f19b85b-e201-45b0-bbb1-c7278f3ec790';
        RAISE EXCEPTION 'assert_verified_deletion_tombstone_was_deleted';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'assert_verified_deletion_tombstone_was_deleted' THEN
            RAISE;
        END IF;
        IF SQLERRM <> 'real deletion requests cannot be deleted' THEN
            RAISE;
        END IF;
    END;
    BEGIN
        UPDATE real_deletion_requests
           SET records_deleted = 0
         WHERE id = '2f19b85b-e201-45b0-bbb1-c7278f3ec790';
        RAISE EXCEPTION 'assert_verified_deletion_tombstone_was_changed';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'assert_verified_deletion_tombstone_was_changed' THEN
            RAISE;
        END IF;
        IF SQLERRM <> 'verified real deletion tombstone is immutable' THEN
            RAISE;
        END IF;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO real_documents (
            id, owner_clerk_user_id, original_filename, source_kind, state,
            sha256, object_size, quarantine_key
        ) VALUES (
            '8167c44e-743c-4ffd-b45a-7e9dc23ead3f',
            'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
            'wrong-key.pdf',
            'controlled_real_upload',
            'quarantined',
            repeat('b', 64),
            512,
            'quarantine/user_2RfWKJREkjKbHZy0Wqa5qrHeAnb/not-the-document.pdf'
        );
        RAISE EXCEPTION 'assert_mismatched_object_key_was_accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO real_audit_events (
            id, owner_clerk_user_id, actor_clerk_user_id, action, target_id,
            request_id, detail
        ) VALUES (
            'ed24cfa5-e79c-468e-a6f0-11c7c8f70529',
            'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
            'user_2RfWKJREkjKbHZy0Wqa5qrHeAnb',
            'upload_received',
            'c2b21f86-66f7-43f5-94a4-4c5f9f9c35af',
            'request-id-unsafe',
            '{"content": "private document text"}'::jsonb
        );
        RAISE EXCEPTION 'assert_content_bearing_audit_was_accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END;
$$;

DO $$
DECLARE
    changed_count INTEGER;
BEGIN
    UPDATE real_audit_events
       SET detail = '{"tampered": true}'::jsonb
     WHERE id = '8fd4b65c-4e64-4a07-88d7-bfa4374b088a';
    GET DIAGNOSTICS changed_count = ROW_COUNT;
    IF changed_count <> 0 THEN
        RAISE EXCEPTION 'application role changed an append-only audit row';
    END IF;
    BEGIN
        TRUNCATE real_audit_events;
        RAISE EXCEPTION 'assert_application_audit_truncate_was_accepted';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;
    END;
END;
$$;

SELECT set_config(
    'hub.owner_clerk_user_id',
    'user_000000000000000000000000000',
    true
);

DO $$
DECLARE
    visible_count INTEGER;
BEGIN
    SELECT count(*) INTO visible_count FROM real_documents;
    IF visible_count <> 0 THEN
        RAISE EXCEPTION 'wrong owner must see zero real documents';
    END IF;
    SELECT count(*) INTO visible_count FROM real_audit_events;
    IF visible_count <> 0 THEN
        RAISE EXCEPTION 'wrong owner must see zero real audit events';
    END IF;
END;
$$;

RESET ROLE;

DO $$
BEGIN
    BEGIN
        UPDATE real_audit_events
           SET detail = '{"tampered": true}'::jsonb
         WHERE id = '8fd4b65c-4e64-4a07-88d7-bfa4374b088a';
        RAISE EXCEPTION 'assert_audit_trigger_did_not_run';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'assert_audit_trigger_did_not_run' THEN
            RAISE;
        END IF;
    END;
    BEGIN
        TRUNCATE real_audit_events;
        RAISE EXCEPTION 'assert_audit_truncate_trigger_did_not_run';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'assert_audit_truncate_trigger_did_not_run' THEN
            RAISE;
        END IF;
        IF SQLERRM <> 'real_audit_events is append-only' THEN
            RAISE;
        END IF;
    END;
END;
$$;

ROLLBACK;
