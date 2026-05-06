# Stage 1: Build the React frontend
FROM node:20-slim AS frontend-build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY --from=frontend-build /app/dist ./dist

EXPOSE 8000
ENV PORT=8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
