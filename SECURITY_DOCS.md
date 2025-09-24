# 🔒 אבטחת הגשת קבצי תיעוד

## ⚠️ אזהרת אבטחה קריטית

**בעיה שנמצאה:** Directory Traversal Vulnerability  
**רמת חומרה:** 🔴 **קריטית (P0)**  
**סטטוס:** ✅ **תוקן**

## הבעיה

הקוד המקורי אפשר למשתמשים לגשת לכל קובץ בשרת דרך path traversal:
```python
# ❌ קוד פגיע - אל תשתמש!
file = DOCS_PATH / file_path  # ../../etc/passwd
if file.exists():
    return FileResponse(file)  # חושף קבצי מערכת!
```

## הפתרון

### אופציה 1: StaticFiles (מומלץ ✅)
```python
from fastapi.staticfiles import StaticFiles

# בטוח - FastAPI מטפל באבטחה
app.mount(
    "/docs-site",
    StaticFiles(directory="site", html=True, check_dir=True),
    name="documentation"
)
```

### אופציה 2: בדיקת Path ידנית
```python
# מאמת שהקובץ בתוך התיקייה המותרת
requested_file = (DOCS_PATH / file_path).resolve()
if not str(requested_file).startswith(str(DOCS_PATH.resolve())):
    return HTTPException(403, "Access denied")
```

## בדיקות אבטחה

הרץ את הבדיקות:
```bash
pytest tests/test_security_docs.py -v
```

הבדיקות כוללות:
- ✅ Directory traversal (`../../etc/passwd`)
- ✅ URL encoding (`%2e%2e%2f`)
- ✅ Null byte injection (`%00`)
- ✅ Windows paths (`..\..\`)
- ✅ Double dots (`....//`)

## המלצות אבטחה

### DO ✅
- השתמש ב-`StaticFiles` של FastAPI
- השתמש ב-`.resolve()` לנרמול paths
- בדוק שה-path נשאר בתיקייה המותרת
- החזר 403 לניסיונות חדירה
- רשום logs לניסיונות חשודים

### DON'T ❌
- אל תשרשר paths ישירות
- אל תסמוך על user input
- אל תחשוף מבנה תיקיות
- אל תחזיר הודעות שגיאה מפורטות

## ניטור

הוסף ניטור לניסיונות חדירה:
```python
if not is_safe_path:
    logger.warning(
        f"Blocked directory traversal attempt: {file_path}",
        extra={"ip": request.client.host}
    )
    # אפשר להוסיף חסימת IP אחרי X ניסיונות
```

## צ'קליסט לביקורת

- [ ] כל ה-paths עוברים `.resolve()`
- [ ] בדיקה שה-path בתיקייה המותרת
- [ ] החזרת 403 לניסיונות חדירה
- [ ] בדיקות אבטחה עוברות
- [ ] אין חשיפת מידע בהודעות שגיאה
- [ ] Logging לניסיונות חשודים

## דיווח על בעיות אבטחה

מצאת בעיית אבטחה? דווח באופן אחראי:
- 📧 security@animal-rescue.com
- 🔐 PGP Key: [public key]
- 🎁 Bug Bounty: כן

---

**תודה ל-@chatgpt-codex-connector על זיהוי הבעיה!** 🙏