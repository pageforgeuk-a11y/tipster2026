#!/bin/bash
# Vercel static build step: collect static files into staticfiles/.
#
# Vercel's build image now ships an externally-managed (uv) Python, so we install
# into a throwaway virtualenv rather than the system interpreter (avoids the
# PEP 668 "externally-managed-environment" error). Database migrations are NOT
# run here — run them once against the managed DB (see README).
set -e

python3 -m venv /tmp/build-venv
. /tmp/build-venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput --clear
