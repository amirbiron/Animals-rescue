#!/bin/bash

# Script to build and serve documentation locally

echo "📚 Animal Rescue Bot - Documentation Server"
echo "=========================================="
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8+ first."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "docs_venv" ]; then
    echo "🔧 Creating virtual environment..."
    python3 -m venv docs_venv
fi

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source docs_venv/bin/activate

# Install dependencies
echo "📦 Installing MkDocs and dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r docs/requirements.txt

# Build the documentation
echo "🔨 Building documentation..."
mkdocs build --clean

# Check if build was successful
if [ $? -ne 0 ]; then
    echo "❌ Documentation build failed!"
    exit 1
fi

echo "✅ Documentation built successfully!"
echo ""
echo "🚀 Starting documentation server..."
echo "📍 Documentation will be available at: http://localhost:8001"
echo "   Press Ctrl+C to stop the server"
echo ""

# Serve the documentation
mkdocs serve --dev-addr localhost:8001