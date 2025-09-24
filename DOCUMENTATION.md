# 📚 אתר התיעוד - הוראות הפעלה

## 🚀 הפעלה מהירה ב-GitHub Pages (מומלץ!)

### 3 צעדים פשוטים:

1. **דחוף את הקוד לגיטהאב**
   ```bash
   git add .
   git commit -m "Add documentation site"
   git push origin main
   ```

2. **הפעל GitHub Pages**
   - לך ל-**Settings** → **Pages** בריפו
   - ב-**Source** בחר: `GitHub Actions`
   - לחץ **Save**

3. **זהו! האתר באוויר** 🎉
   - חכה 2-3 דקות
   - האתר זמין ב: `https://[username].github.io/[repo-name]/`

---

## 🖥️ הרצה מקומית (לפיתוח)

### אופציה 1: Docker (הכי פשוט)
```bash
./run_docs_docker.sh
```

### אופציה 2: התקנה מקומית
```bash
# התקנה חד-פעמית
./install_docs.sh
# בחר אופציה 2 (pip --user)

# הרצה
python3 -m mkdocs serve
```

### אופציה 3: התקנה ידנית
```bash
# התקנת MkDocs
pip install --user mkdocs mkdocs-material

# הרצת השרת
mkdocs serve
```

**האתר יהיה זמין ב:** http://localhost:8000

---

## 📁 מבנה התיעוד

```
docs/
├── index.md              # 🏠 דף הבית
├── getting-started.md    # 🚀 התחלה מהירה  
├── quickstart.md         # ⚡ מדריך 5 דקות
├── architecture.md       # 🏗️ ארכיטקטורה
├── admin-guide.md        # 👑 מדריך למנהלים
├── dev-guide.md          # 💻 מדריך למפתחים
├── ops.md               # 🔧 תפעול ודיפלוי
├── api-reference.md     # 📡 תיעוד API
└── faq.md               # ❓ שאלות נפוצות
```

---

## ✏️ עריכת התיעוד

1. **ערוך** קבצי Markdown בתיקיית `docs/`
2. **בדוק** מקומית: `mkdocs serve`
3. **דחוף** לגיטהאב - העדכון יהיה אוטומטי!

### הוספת דף חדש:
1. צור קובץ `docs/new-page.md`
2. הוסף ל-`mkdocs.yml`:
   ```yaml
   nav:
     - 'דף חדש': new-page.md
   ```

---

## 🎨 תכונות האתר

- ✨ **עיצוב Material Design** - נקי ומודרני
- 🌙 **מצב כהה/בהיר** - החלפה אוטומטית
- 🔍 **חיפוש חכם** - בעברית, אנגלית וערבית
- 📱 **Responsive** - מותאם למובייל
- 📊 **תרשימי Mermaid** - דיאגרמות אינטראקטיביות
- 🎯 **RTL מלא** - תמיכה מושלמת בעברית

---

## 🔧 פתרון בעיות

### האתר לא עולה ב-GitHub Pages?
1. בדוק ב-**Actions** שה-workflow רץ בהצלחה
2. וודא ש-**Settings → Pages → Source = GitHub Actions**
3. המתן עד 10 דקות בפעם הראשונה

### שגיאה בבנייה?
```bash
# בדוק את התחביר
mkdocs build --strict

# ראה שגיאות מפורטות
mkdocs serve --verbose
```

### החיפוש לא עובד?
- נקה cache של הדפדפן (Ctrl+F5)
- וודא שהשפה נתמכת ב-`mkdocs.yml`

---

## 🚢 אפשרויות פריסה נוספות

### Render (Static Site)
```bash
# Build Command:
pip install mkdocs mkdocs-material && mkdocs build

# Publish Directory:
site
```

### Netlify
```bash
# Build Command:
mkdocs build

# Publish Directory:
site
```

### Vercel
```json
{
  "buildCommand": "pip install mkdocs mkdocs-material && mkdocs build",
  "outputDirectory": "site"
}
```

---

## 📦 דרישות מערכת

- **Python** 3.8+
- **pip** או **pipx**
- **Git** (לפריסה)

### Dependencies (מותקנות אוטומטית):
- `mkdocs` - מנוע האתר
- `mkdocs-material` - תמה
- `mkdocs-minify-plugin` - אופטימיזציה

---

## 🤝 תרומה לתיעוד

1. **Fork** את הריפו
2. **ערוך** את הקבצים ב-`docs/`
3. **בדוק** מקומית: `mkdocs serve`
4. **שלח** Pull Request

### כללי כתיבה:
- כתוב בעברית פשוטה וברורה
- השתמש בכותרות היררכיות (`#`, `##`, `###`)
- הוסף דוגמאות קוד כשרלוונטי
- השתמש באימוג'ים לחיזוק המסר 🎯

---

## 📞 תמיכה

- **בעיות טכניות:** [GitHub Issues](https://github.com/animal-rescue-bot/issues)
- **שאלות:** [Discussions](https://github.com/animal-rescue-bot/discussions)
- **מייל:** docs@animal-rescue.com

---

## 📄 רישיון

התיעוד תחת רישיון [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

---

<div align="center">
  <h3>🎉 זהו! האתר מוכן לשימוש</h3>
  <p>תוך 3 דקות יהיה לך אתר תיעוד מקצועי ויפהפה!</p>
  <br>
  <strong>בהצלחה! 🚀</strong>
</div>