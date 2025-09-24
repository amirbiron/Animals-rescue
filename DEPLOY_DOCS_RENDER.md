# 📚 פריסת אתר התיעוד ב-Render

## 🎯 שתי אפשרויות להעלאת התיעוד

### אופציה 1: **Static Site נפרד** (מומלץ! ✨)

#### צעד 1: יצירת Static Site חדש ב-Render

1. היכנס ל-[Render Dashboard](https://dashboard.render.com)
2. לחץ על **"New +"** → **"Static Site"**
3. חבר את הריפו מ-GitHub
4. הגדרות:
   - **Name**: `animal-rescue-docs`
   - **Branch**: `main`
   - **Build Command**: 
     ```bash
     pip install mkdocs mkdocs-material mkdocs-minify-plugin && mkdocs build
     ```
   - **Publish Directory**: `site`

5. לחץ **"Create Static Site"**

#### צעד 2: המתן לבנייה
- הבנייה תיקח 2-3 דקות
- כשיסתיים, תקבל URL כמו: `https://animal-rescue-docs.onrender.com`

**זהו! האתר באוויר! 🎉**

---

### אופציה 2: **כחלק מה-Web Service הקיים**

#### צעד 1: עדכון Build Command

בהגדרות ה-Web Service שלך ב-Render, עדכן את ה-**Build Command**:

```bash
pip install -r requirements.txt && pip install mkdocs mkdocs-material mkdocs-minify-plugin && mkdocs build
```

#### צעד 2: הוספת Route לאפליקציה

הוסף לקובץ `/app/main.py` (אחרי שאר ה-routers):

```python
# Serve documentation
from fastapi.staticfiles import StaticFiles
import os

if os.path.exists("site"):
    app.mount("/docs-site", StaticFiles(directory="site", html=True), name="documentation")
    logger.info("📚 Documentation mounted at /docs-site")
```

#### צעד 3: Deploy מחדש
- לחץ על **"Manual Deploy"** → **"Deploy latest commit"**

#### צעד 4: גישה לתיעוד
האתר יהיה זמין ב:
```
https://your-app.onrender.com/docs-site
```

---

## 🔍 בדיקה שהכל עובד

### לאחר הפריסה, בדוק:

1. **דף הבית**: `https://your-docs-url.onrender.com`
2. **חיפוש עובד**: נסה לחפש "התקנה"
3. **ניווט תקין**: בדוק שכל הקישורים עובדים
4. **תמונות ותרשימים**: וודא שהכל נטען

---

## 🚀 עדכון אוטומטי

### הגדרת Auto-Deploy:

1. ב-Render Dashboard, היכנס להגדרות השירות
2. תחת **"Build & Deploy"**
3. הפעל **"Auto-Deploy"** → **"Yes"**

עכשיו כל push ל-`main` יעדכן את האתר אוטומטית! 

---

## 💡 טיפים חשובים

### אם הבנייה נכשלת:

1. **בדוק את הלוגים** ב-Render Dashboard
2. **שגיאות נפוצות**:
   - חסרה תלות? הוסף ל-Build Command
   - שגיאת תחביר ב-Markdown? תקן ודחוף מחדש

### לביצועים טובים יותר:

1. הפעל **CDN** בהגדרות Render
2. הגדר **Custom Domain** (אם יש לך)
3. הוסף **Cache Headers** להגדרות

---

## 📊 מעקב וניטור

### ב-Render Dashboard תוכל לראות:
- **Build Logs** - מה קורה בבנייה
- **Traffic** - כמה אנשים נכנסים
- **Performance** - זמני טעינה
- **Errors** - אם משהו לא עובד

---

## 🎯 המלצה חמה

**השתמש באופציה 1 (Static Site)** כי:
- ✅ חינם לחלוטין!
- ✅ מהיר יותר (CDN מובנה)
- ✅ פשוט לניהול
- ✅ URL נפרד ונקי
- ✅ לא משפיע על ה-API הראשי

---

## 🆘 נתקעת?

**הלוגים ב-Render אומרים "Module not found"?**
```bash
# הוסף ל-Build Command:
pip install --upgrade pip && pip install mkdocs mkdocs-material
```

**האתר לא נטען?**
- בדוק שה-**Publish Directory** מוגדר ל-`site`
- וודא שה-Build Command מריץ `mkdocs build`

**עדיין בעיה?**
- צור [Issue בגיטהאב](https://github.com/animal-rescue-bot/issues)
- או שלח מייל ל-support@animal-rescue.com

---

## ✨ סיכום - הפקודה המלאה

**ב-Render, הגדר Static Site עם:**

**Build Command:**
```bash
pip install mkdocs mkdocs-material mkdocs-minify-plugin && mkdocs build
```

**Publish Directory:**
```
site
```

**זהו! תוך 3 דקות האתר שלך באוויר! 🚀**