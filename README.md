# DubeyAI

Production-ready Django chatbot using NVIDIA's OpenAI-compatible API.

## Local setup

1. Create a virtual environment and install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and set `SECRET_KEY` and `NVIDIA_API_KEY`.

3. Prepare and run Django:

   ```powershell
   python manage.py migrate
   python manage.py runserver
   ```

## Render

Create a Blueprint from `render.yaml`, provide `NVIDIA_API_KEY`, and deploy. The
Blueprint provisions PostgreSQL, collects static files, runs migrations, and
starts Gunicorn.
