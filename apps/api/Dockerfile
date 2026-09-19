FROM python:3.12-slim
WORKDIR /workspace
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . psycopg[binary]
COPY apps ./apps
EXPOSE 3000
CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "3000"]
