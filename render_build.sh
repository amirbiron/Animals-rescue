##!/usr/bin/env bash
set -o errexit

pip install -U pip setuptools wheel
pip install --prefer-binary -r requirements.txt
# אל תוריד מודלים בזמן build
# python -m spacy download he_core_news_sm
