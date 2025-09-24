-- ============================================================================
-- עדכון alert_channels לכל הארגונים עם מספר טלפון ל־WhatsApp+SMS בלבד
-- הרצה:
--   psql -h <host> -p <port> -U <user> -d <db> -f scripts/update_alert_channels.sql
-- או (אם יש משתני סביבה):
--   PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f scripts/update_alert_channels.sql
-- הערה: העמודה alert_channels היא text[] (ARRAY), לא JSON.
-- ============================================================================

BEGIN;

DO $$
DECLARE
    empty_before INTEGER;
    updated_rows INTEGER;
    exact_after INTEGER;
BEGIN
    -- כמה ארגונים עם טלפון וערוצי התראות ריקים (array length = 0)
    SELECT COUNT(*) INTO empty_before
    FROM organizations
    WHERE primary_phone IS NOT NULL
      AND btrim(primary_phone) <> ''
      AND COALESCE(array_length(alert_channels, 1), 0) = 0;

    -- עדכון: רק WhatsApp ואז SMS (סדר עדיפות) – מבלי לדרוס ערכים קיימים
    UPDATE organizations
    SET alert_channels = ARRAY['whatsapp','sms']
    WHERE primary_phone IS NOT NULL
      AND btrim(primary_phone) <> ''
      AND COALESCE(array_length(alert_channels, 1), 0) = 0;  -- עדכן רק כש-ARRAY ריק/NULL

    GET DIAGNOSTICS updated_rows = ROW_COUNT;

    -- אימות: כמה כעת בדיוק שווים ל-['whatsapp','sms']
    SELECT COUNT(*) INTO exact_after
    FROM organizations
    WHERE primary_phone IS NOT NULL
      AND btrim(primary_phone) <> ''
      AND alert_channels = ARRAY['whatsapp','sms'];

    RAISE NOTICE 'Organizations with phone and empty channels before: %', empty_before;
    RAISE NOTICE 'Rows updated (set to whatsapp,sms): %', updated_rows;
    RAISE NOTICE 'Organizations now exactly whatsapp,sms: %', exact_after;
END $$;

COMMIT;

-- סוף

