#!/bin/bash

echo "🐳 מריץ את אתר התיעוד עם Docker"
echo "=================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker לא מותקן"
    echo "   להתקנה: https://docs.docker.com/get-docker/"
    exit 1
fi

echo "🚀 מפעיל את האתר..."
echo ""

# Run MkDocs in Docker container
docker run --rm -it \
    -p 8000:8000 \
    -v ${PWD}:/docs \
    squidfunk/mkdocs-material:latest \
    serve --dev-addr 0.0.0.0:8000

echo ""
echo "✅ האתר זמין ב: http://localhost:8000"