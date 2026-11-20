# Quote Clash

Upload 2 to 3 vendor quotes. Quote Clash lines them up apples to apples, flags hidden costs and risky
terms, and drafts a negotiation email.

## Run locally

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then add your GEMINI_API_KEY
uvicorn app.main:app --reload
pytest
```

Regenerate the sample quotes with `python scripts/make_sample_quotes.py`.
Measure extraction accuracy with `python scripts/eval_extraction.py` (calls the real model).

## Deploy on Render (free tier, native Python runtime)

1. Push this repo to GitHub.
2. In the Render dashboard choose New, then Blueprint, and select the repo. Render reads `render.yaml`.
   Or choose New, then Web Service, and use: runtime Python 3, build command
   `pip install -r requirements.txt`, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`,
   instance type Free, health check path `/health`.
3. Set the `GEMINI_API_KEY` environment variable in the dashboard. Never commit it.
4. Deploy, then open the `onrender.com` URL.

The free tier sleeps after about 15 minutes without traffic, so the first request can take around a minute.

## Privacy

Quotes are processed in memory and never stored. The app uses the Gemini API free tier, where Google may use
prompts to improve its products, so do not upload confidential quotes. Use the built-in sample quotes to demo.
