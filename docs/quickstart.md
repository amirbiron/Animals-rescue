# מדריך מהיר - 5 דקות ⚡

רוצה להתחיל מהר? הנה המדריך הכי קצר להפעלת המערכת!

## 🎯 בחר את המסלול שלך

=== "אני רוצה לדווח על בעל חיים"

    ### 30 שניות להתחלה
    
    1. **פתח טלגרם** 📱
    2. **חפש** `@AnimalRescueBot`
    3. **לחץ** Start
    4. **דווח!** 🚀
    
    זהו! אתה מוכן לדווח על בעלי חיים במצוקה.

=== "אני מפתח"

    ### 3 דקות להתקנה
    
    ```bash
    # Clone
    git clone https://github.com/animal-rescue-bot/animal-rescue-bot.git
    cd animal-rescue-bot
    
    # Setup
    python3 -m venv venv && source venv/bin/activate
    pip install -r requirements.txt
    
    # Configure
    cp .env.example .env
    # ערוך את .env עם המפתחות שלך
    
    # Run
    docker-compose up -d
    uvicorn app.main:app --reload
    ```
    
    🎉 המערכת רצה על http://localhost:8000

=== "אני מנהל ארגון"

    ### 2 דקות להרשמה
    
    1. **מלא טופס** ב[קישור הזה](https://forms.gle/AnimalRescueOrg)
    2. **המתן לאישור** (עד 24 שעות)
    3. **קבל גישה** ללוח הבקרה
    4. **התחל לקבל דיווחים!** 📬

## 🚦 בדיקה מהירה

### בדוק שהכל עובד:

```bash
# בדיקת API
curl http://localhost:8000/health

# בדיקת בוט
curl https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe
```

✅ קיבלת תשובה? מעולה! המערכת מוכנה.

## 🆘 נתקעת?

- **תיעוד מלא**: [Getting Started](getting-started.md)
- **צ'אט תמיכה**: [@AnimalRescueSupport](https://t.me/AnimalRescueSupport)
- **וואטסאפ**: [+972-50-123-4567](https://wa.me/972501234567)

---

<div align="center">
  <h2>⏱️ סיימת ב-5 דקות? כל הכבוד! 🎊</h2>
  <p>עכשיו לך להציל חיים 💪</p>
</div>