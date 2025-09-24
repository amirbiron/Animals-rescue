#!/bin/bash
# Script for building docs on Render

echo "📚 Building Documentation Site"
echo "=============================="

# Install MkDocs and dependencies
echo "📦 Installing MkDocs..."
pip install mkdocs mkdocs-material mkdocs-minify-plugin

# Build the static site
echo "🔨 Building static site..."
mkdocs build --clean

# Check if build was successful
if [ -d "site" ]; then
    echo "✅ Documentation built successfully!"
    echo "📁 Static files are in: ./site"
    ls -la site/
else
    echo "❌ Build failed!"
    exit 1
fi