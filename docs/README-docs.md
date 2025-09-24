# 📚 תיעוד - בוט חילוץ בעלי חיים

תיקייה זו מכילה את כל התיעוד של מערכת בוט חילוץ בעלי חיים.

## 🏗️ מבנה התיעוד

```
docs/
├── index.md              # דף הבית
├── getting-started.md    # התחלה מהירה
├── quickstart.md        # מדריך 5 דקות
├── architecture.md      # ארכיטקטורה
├── admin-guide.md       # מדריך למנהלים
├── dev-guide.md         # מדריך למפתחים
├── ops.md              # תפעול ודיפלוי
├── faq.md              # שאלות נפוצות
└── requirements.txt    # תלויות לבניית התיעוד
```

## 🚀 הרצה מקומית

### אופציה 1: סקריפט אוטומטי
```bash
./scripts/serve_docs.sh
```

### אופציה 2: ידני
```bash
# התקנת תלויות
pip install -r docs/requirements.txt

# בניית התיעוד
mkdocs build

# הרצת שרת פיתוח
mkdocs serve
```

התיעוד יהיה זמין ב: http://localhost:8000

## 📝 עריכת התיעוד

1. **ערוך** את קבצי ה-Markdown בתיקיית `docs/`
2. **הוסף** דפים חדשים וערוך את `mkdocs.yml` כדי לכלול אותם בניווט
3. **בדוק** את השינויים עם `mkdocs serve`
4. **בצע commit** ו-push - הדיפלוי יתבצע אוטומטית

## 🎨 עיצוב ותמה

אנחנו משתמשים ב-[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) עם התאמות:
- תמיכה ב-RTL לעברית
- צבעי נושא ירוקים (חילוץ בעלי חיים)
- מצב כהה/בהיר
- חיפוש בעברית, אנגלית וערבית

## 🔧 תוספים פעילים

- **search** - חיפוש רב-לשוני
- **minify** - מזעור HTML לביצועים
- **mermaid** - תרשימי זרימה
- **admonition** - הערות והתראות
- **pymdownx** - תחביר Markdown מורחב

## 📦 בניה לפרודקשן

```bash
# בניית האתר הסטטי
mkdocs build --strict

# הקבצים יהיו ב-site/
ls -la site/
```

## 🚢 דיפלוי

הדיפלוי מתבצע אוטומטית דרך GitHub Actions:
1. Push לענף `main`
2. GitHub Actions בונה את התיעוד
3. פריסה ל-GitHub Pages

האתר זמין ב: https://animal-rescue-bot.github.io/

## 📄 רישיון

התיעוד תחת רישיון [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

---

<div align="center">
  <strong>נבנה עם ❤️ עבור קהילת חילוץ בעלי החיים</strong>
</div>