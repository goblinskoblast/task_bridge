# Stage 1: Build React app
FROM node:18-alpine AS frontend-builder

WORKDIR /app/webapp

# Copy package files
COPY webapp/package*.json ./

# Install dependencies
RUN npm ci

# Copy source files
COPY webapp/ ./

# Build React app
RUN npm run build

# Stage 2: Python app
FROM python:3.10-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy built React app from frontend-builder stage
COPY --from=frontend-builder /app/webapp/dist /app/webapp/dist

# Create data directory
RUN mkdir -p /app/data

# Environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "main.py"]
