#!/bin/bash

echo "🚀 התקנת אתר התיעוד - בוט חילוץ בעלי חיים"
echo "============================================"
echo ""

# Check Python version
if command -v python3 &> /dev/null; then
    echo "✅ Python נמצא: $(python3 --version)"
else
    echo "❌ Python 3 לא נמצא. נדרש Python 3.8+"
    echo "   להתקנה: https://www.python.org/downloads/"
    exit 1
fi

echo ""
echo "📦 מתקין את MkDocs..."
echo ""

# Try different installation methods
echo "בחר אופציית התקנה:"
echo "1) pipx (מומלץ - מבודד ונקי)"
echo "2) pip --user (התקנה למשתמש)"
echo "3) pip עם venv (סביבה וירטואלית)"
echo "4) pip גלובלי (דורש sudo)"
echo ""
read -p "בחר אופציה (1-4): " choice

case $choice in
    1)
        echo "📦 מתקין עם pipx..."
        if ! command -v pipx &> /dev/null; then
            echo "מתקין pipx..."
            python3 -m pip install --user pipx
            python3 -m pipx ensurepath
        fi
        pipx install mkdocs
        pipx inject mkdocs mkdocs-material mkdocs-minify-plugin
        echo "✅ הושלם! הרץ: mkdocs serve"
        ;;
    
    2)
        echo "📦 מתקין עם pip --user..."
        python3 -m pip install --user mkdocs mkdocs-material mkdocs-minify-plugin
        echo "✅ הושלם! הרץ: python3 -m mkdocs serve"
        ;;
    
    3)
        echo "📦 יוצר סביבה וירטואלית..."
        # Try to create venv
        if python3 -m venv docs_venv 2>/dev/null; then
            source docs_venv/bin/activate
            pip install mkdocs mkdocs-material mkdocs-minify-plugin
            echo "✅ הושלם!"
            echo "   להפעלה: source docs_venv/bin/activate && mkdocs serve"
        else
            echo "❌ לא ניתן ליצור venv. נסה:"
            echo "   sudo apt install python3-venv"
            echo "   או השתמש באופציה אחרת"
        fi
        ;;
    
    4)
        echo "📦 מתקין גלובלית (דורש sudo)..."
        sudo python3 -m pip install mkdocs mkdocs-material mkdocs-minify-plugin
        echo "✅ הושלם! הרץ: mkdocs serve"
        ;;
    
    *)
        echo "❌ אופציה לא תקינה"
        exit 1
        ;;
esac

echo ""
echo "=========================================="
echo "🎉 מוכן להרצה!"
echo ""
echo "להרצת האתר:"
echo "  mkdocs serve"
echo ""
echo "האתר יהיה זמין ב:"
echo "  http://localhost:8000"
echo "=========================================="