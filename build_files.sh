#!/bin/bash
# Vercel build step: install deps and collect static files into staticfiles/.
# Database migrations are NOT run here — run them once against the managed DB
# (see README) so a build never blocks on DB availability.
set -e

python3 -m pip install -r requirements.txt
python3 manage.py collectstatic --noinput --clear
