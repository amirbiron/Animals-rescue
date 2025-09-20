-- ============================================================================
-- סקריפט להכנסת ארגונים ראשוניים למסד הנתונים
-- ============================================================================
-- 
-- הרצה: psql -U postgres -d animal_rescue -f scripts/initial_data.sql
--

-- נקה נתונים קיימים (אופציונלי - הסר הערה אם רוצה להתחיל מאפס)
-- TRUNCATE organizations CASCADE;

-- ============================================================================
-- הכנסת ארגונים עם פרטי התקשרות מלאים
-- ============================================================================

INSERT INTO organizations (
    id,
    name,
    name_en,
    organization_type,
    primary_phone,
    emergency_phone,
    email,
    website,
    address,
    city,
    latitude,
    longitude,
    service_radius_km,
    is_24_7,
    is_active,
    is_verified,
    specialties,
    alert_channels,
    created_at,
    updated_at
) VALUES 
-- תל אביב והמרכז
(
    gen_random_uuid(),
    'מרכז וטרינרי תל אביב',
    'Tel Aviv Veterinary Center',
    'emergency_vet',
    '03-5223355',
    '03-5223355',
    'info@vetcenter-tlv.co.il',
    'https://www.vetcenter.co.il',
    'דרך נמיר 125, תל אביב',
    'תל אביב',
    32.1134, 34.8053,
    15.0,
    true,
    true,
    true,
    ARRAY['dogs', 'cats', 'birds', 'exotic'],
    ARRAY['email', 'sms'],
    NOW(),
    NOW()
),
(
    gen_random_uuid(),
    'אגודת צער בעלי חיים בישראל',
    'SPCA Israel',
    'rescue_org',
    '03-5136500',
    NULL,
    'info@spca.org.il',
    'https://www.spca.org.il',
    'הרצל 159, תל אביב',
    'תל אביב',
    32.0565, 34.7701,
    50.0,
    false,
    true,
    true,
    ARRAY['dogs', 'cats', 'wildlife'],
    ARRAY['email', 'telegram'],
    NOW(),
    NOW()
),
(
    gen_random_uuid(),
    'תנו לחיות לחיות',
    'Let the Animals Live',
    'rescue_org',
    '03-7441010',
    NULL,
    'office@letlive.org.il',
    'https://www.letlive.org.il',
    'יגאל אלון 157, תל אביב',
    'תל אביב',
    32.0708, 34.7945,
    30.0,
    false,
    true,
    true,
    ARRAY['dogs', 'cats'],
    ARRAY['email', 'whatsapp'],
    NOW(),
    NOW()
),

-- ירושלים
(
    gen_random_uuid(),
    'מרפאה וטרינרית עירונית ירושלים',
    'Jerusalem Municipal Veterinary Clinic',
    'government',
    '02-6296293',
    NULL,
    'vetjer@jerusalem.muni.il',
    NULL,
    'אגריפס 42, ירושלים',
    'ירושלים',
    31.7833, 35.2167,
    20.0,
    false,
    true,
    true,
    ARRAY['dogs', 'cats'],
    ARRAY['email'],
    NOW(),
    NOW()
),

-- חיפה
(
    gen_random_uuid(),
    'המרפאה הווטרינרית חיפה',
    'Haifa Veterinary Clinic',
    'vet_clinic',
    '04-8522038',
    NULL,
    'info@haifavet.co.il',
    NULL,
    'שדרות הנשיא 134, חיפה',
    'חיפה',
    32.8073, 34.9897,
    15.0,
    false,
    true,
    false,
    ARRAY['dogs', 'cats', 'birds'],
    ARRAY['email', 'sms'],
    NOW(),
    NOW()
),

-- באר שבע והדרום
(
    gen_random_uuid(),
    'מרפאה וטרינרית באר שבע',
    'Beer Sheva Veterinary Clinic',
    'vet_clinic',
    '08-6234567',
    NULL,
    'vetbs@gmail.com',
    NULL,
    'רגר 22, באר שבע',
    'באר שבע',
    31.2530, 34.7915,
    25.0,
    false,
    true,
    false,
    ARRAY['dogs', 'cats'],
    ARRAY['email'],
    NOW(),
    NOW()
),

-- אילת
(
    gen_random_uuid(),
    'מרפאה וטרינרית אילת',
    'Eilat Veterinary Clinic',
    'vet_clinic',
    '08-6340454',
    NULL,
    'veteilat@gmail.com',
    NULL,
    'השיטה 5, אילת',
    'אילת',
    29.5581, 34.9482,
    30.0,
    false,
    true,
    false,
    ARRAY['dogs', 'cats', 'exotic'],
    ARRAY['email'],
    NOW(),
    NOW()
),

-- רחובות - בית חולים וטרינרי
(
    gen_random_uuid(),
    'בית החולים הווטרינרי האוניברסיטאי',
    'University Veterinary Hospital',
    'animal_hospital',
    '08-9489560',
    '08-9489560',
    'vth@mail.huji.ac.il',
    'https://www.vth.co.il',
    'דרך האוניברסיטה, רחובות',
    'רחובות',
    31.9045, 34.8086,
    40.0,
    true,
    true,
    true,
    ARRAY['dogs', 'cats', 'birds', 'exotic', 'livestock'],
    ARRAY['email', 'sms', 'whatsapp'],
    NOW(),
    NOW()
),
-- נתניה
(
    gen_random_uuid(),
    'וטרינר 24/7 נתניה',
    '24/7 Vet Netanya',
    'emergency_vet',
    '09-8855500',
    '09-8855500',
    'emergency@vet247.co.il',
    NULL,
    'הרצל 48, נתניה',
    'נתניה',
    32.3215, 34.8532,
    20.0,
    true,
    true,
    false,
    ARRAY['dogs', 'cats'],
    ARRAY['email', 'sms'],
    NOW(),
    NOW()
),

-- אשדוד
(
    gen_random_uuid(),
    'וטרינר חירום אשדוד',
    'Ashdod Emergency Vet',
    'emergency_vet',
    '08-8566677',
    '08-8566677',
    'emergency@ashdodvet.co.il',
    NULL,
    'הבנים 15, אשדוד',
    'אשדוד',
    31.7969, 34.6439,
    25.0,
    true,
    true,
    false,
    ARRAY['dogs', 'cats'],
    ARRAY['email'],
    NOW(),
    NOW()
),

-- ראשון לציון
(
    gen_random_uuid(),
    'מקלט כלבים עירוני ראשון לציון',
    'Rishon LeZion Dog Shelter',
    'animal_shelter',
    '03-9547878',
    NULL,
    'dogs@rishonlezion.muni.il',
    NULL,
    'דרך יבנה, ראשון לציון',
    'ראשון לציון',
    31.9730, 34.7925,
    15.0,
    false,
    true,
    true,
    ARRAY['dogs'],
    ARRAY['email'],
    NOW(),
    NOW()
),

-- רמת גן - ספארי
(
    gen_random_uuid(),
    'מרפאת חיות בר - ספארי',
    'Safari Wildlife Clinic',
    'vet_clinic',
    '03-6423333',
    NULL,
    'wildlife@safari.co.il',
    'https://www.safari.co.il',
    'ספארי רמת גן',
    'רמת גן',
    32.0681, 34.8094,
    50.0,
    false,
    true,
    true,
    ARRAY['wildlife', 'exotic', 'birds'],
    ARRAY['email'],
    NOW(),
    NOW()
),

-- חולון
(
    gen_random_uuid(),
    'SOS חיות',
    'SOS Animals',
    'rescue_org',
    '03-7477477',
    NULL,
    'help@sos-animals.org.il',
    'https://www.sos-animals.org.il',
    'המלאכה 3, חולון',
    'חולון',
    32.0114, 34.7765,
    25.0,
    false,
    true,
    true,
    ARRAY['dogs', 'cats'],
    ARRAY['email', 'whatsapp'],
    NOW(),
    NOW()
),

-- רעננה
(
    gen_random_uuid(),
    'עמותת חבר',
    'Haver Organization',
    'rescue_org',
    '09-7467949',
    NULL,
    'info@haver.org.il',
    'https://www.haver.org.il',
    'התעשייה 8, רעננה',
    'רעננה',
    32.1847, 34.8707,
    20.0,
    false,
    true,
    true,
    ARRAY['dogs', 'cats'],
    ARRAY['email'],
    NOW(),
    NOW()
);

-- ============================================================================
-- הוספת דוגמאות למשתמשים (אופציונלי)
-- ============================================================================

INSERT INTO users (
    id,
    telegram_user_id,
    username,
    full_name,
    email,
    phone,
    role,
    language,
    is_active,
    is_verified,
    trust_score,
    created_at,
    updated_at
) VALUES
(
    gen_random_uuid(),
    123456789,
    'test_user',
    'משתמש בדיקה',
    'test@example.com',
    '050-1234567',
    'reporter',
    'he',
    true,
    true,
    8.0,
    NOW(),
    NOW()
),
(
    gen_random_uuid(),
    987654321,
    'vet_admin',
    'מנהל וטרינרי',
    'admin@vetcenter.co.il',
    '050-9876543',
    'org_admin',
    'he',
    true,
    true,
    10.0,
    NOW(),
    NOW()
);

-- ============================================================================
-- סטטיסטיקות
-- ============================================================================

DO $$
DECLARE
    org_count INTEGER;
    with_phone INTEGER;
    with_email INTEGER;
    active_count INTEGER;
    emergency_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO org_count FROM organizations;
    SELECT COUNT(*) INTO with_phone FROM organizations WHERE primary_phone IS NOT NULL;
    SELECT COUNT(*) INTO with_email FROM organizations WHERE email IS NOT NULL;
    SELECT COUNT(*) INTO active_count FROM organizations WHERE is_active = true;
    SELECT COUNT(*) INTO emergency_count FROM organizations WHERE is_24_7 = true;
    
    RAISE NOTICE '';
    RAISE NOTICE '====================================';
RAISE NOTICE 'סיכום הכנסת נתונים:';
    RAISE NOTICE '====================================';
    RAISE NOTICE 'סה"כ ארגונים: %', org_count;
    RAISE NOTICE 'עם טלפון: %', with_phone;
    RAISE NOTICE 'עם מייל: %', with_email;
    RAISE NOTICE 'פעילים: %', active_count;
    RAISE NOTICE 'חירום 24/7: %', emergency_count;
    RAISE NOTICE '====================================';
END $$;
