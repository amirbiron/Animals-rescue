#!/bin/bash

echo "🧪 בודק את אתר התיעוד..."
echo "=========================="
echo ""

# Check if MkDocs is installed
if ! command -v mkdocs &> /dev/null; then
    echo "⚠️  MkDocs לא מותקן. מריץ עם Docker..."
    docker run --rm -v ${PWD}:/docs squidfunk/mkdocs-material:latest build
else
    echo "🔨 בונה את האתר..."
    mkdocs build --verbose
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ הבנייה הצליחה!"
    echo ""
    echo "📁 האתר נבנה בתיקיית: site/"
    echo "📊 סטטיסטיקות:"
    echo "   - קבצי HTML: $(find site -name "*.html" | wc -l)"
    echo "   - גודל כולל: $(du -sh site | cut -f1)"
    echo ""
    echo "🚀 להרצה מקומית: mkdocs serve"
else
    echo ""
    echo "❌ הבנייה נכשלה!"
    echo ""
    echo "💡 טיפים לתיקון:"
    echo "   1. בדוק שכל הקבצים ב-nav קיימים"
    echo "   2. בדוק תחביר Markdown"
    echo "   3. הרץ: mkdocs build --verbose לפרטים"
fi