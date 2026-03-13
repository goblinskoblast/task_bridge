#!/bin/bash
# Production deployment script for TaskBridge with OpenClaw
# Run this on your Linux server

set -e

echo "============================================"
echo "TaskBridge + OpenClaw Production Setup"
echo "============================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo $0)"
    exit 1
fi

# Install Docker if not installed
if ! command -v docker &> /dev/null; then
    echo "[1/5] Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
else
    echo "[1/5] Docker already installed"
fi

# Install Docker Compose if not installed
if ! command -v docker-compose &> /dev/null; then
    echo "[2/5] Installing Docker Compose..."
    apt-get update
    apt-get install -y docker-compose
else
    echo "[2/5] Docker Compose already installed"
fi

# Clone repository if not exists
if [ ! -d "taskbridge" ]; then
    echo "[3/5] Cloning repository..."
    read -p "Enter your GitHub repository URL: " REPO_URL
    git clone $REPO_URL taskbridge
    cd taskbridge
else
    echo "[3/5] Repository already exists, pulling latest..."
    cd taskbridge
    git pull
fi

# Configure .env
echo "[4/5] Configuring environment..."

if [ ! -f ".env" ]; then
    echo "Creating .env file..."

    read -p "Enter your Telegram Bot Token: " BOT_TOKEN
    read -p "Enter your OpenAI API Key: " OPENAI_API_KEY
    read -p "Use local OpenClaw (y) or ngrok URL (n)? [y/n]: " USE_LOCAL

    if [ "$USE_LOCAL" = "y" ]; then
        OPENCLAW_URL="http://openclaw:3000"
        echo "Using local OpenClaw in Docker network"
    else
        read -p "Enter your ngrok URL (e.g., https://abc123.ngrok.io): " OPENCLAW_URL
        echo "Using remote OpenClaw via ngrok"
    fi

    cat > .env <<EOF
# Telegram Bot Configuration
BOT_TOKEN=$BOT_TOKEN

# AI Provider Configuration
AI_PROVIDER=openclaw

# OpenClaw Configuration
OPENCLAW_BASE_URL=$OPENCLAW_URL
OPENCLAW_MODEL=openai/gpt-4o
OPENCLAW_TIMEOUT=60

# OpenAI API Key
OPENAI_API_KEY=$OPENAI_API_KEY

# Database
DATABASE_URL=sqlite:///./data/taskbridge.db

# Server
HOST=0.0.0.0
PORT=8000
USE_WEBHOOK=False

# Other
LOG_LEVEL=INFO
TIMEZONE=Europe/Moscow
EOF
    echo "✓ .env file created"
else
    echo "✓ .env file already exists"
    echo "  You can edit it with: nano .env"
fi

# Modify docker-compose.yml based on setup choice
if [ "$USE_LOCAL" != "y" ]; then
    echo "Configuring docker-compose.yml for remote OpenClaw..."

    # Create backup
    cp docker-compose.yml docker-compose.yml.backup

    # Comment out openclaw service and depends_on
    sed -i 's/^  openclaw:/#  openclaw:/g' docker-compose.yml
    sed -i 's/^    image: ghcr/#    image: ghcr/g' docker-compose.yml
    sed -i 's/^    restart:/#    restart:/g' docker-compose.yml
    sed -i 's/^    environment:/#    environment:/g' docker-compose.yml
    sed -i 's/^      - OPENAI/#      - OPENAI/g' docker-compose.yml
    sed -i 's/^    ports:/#    ports:/g' docker-compose.yml
    sed -i 's/^    volumes:/#    volumes:/g' docker-compose.yml
    sed -i 's/^    networks:/#    networks:/g' docker-compose.yml
    sed -i 's/^    depends_on:/#    depends_on:/g' docker-compose.yml
    sed -i 's/^      - openclaw/#      - openclaw/g' docker-compose.yml

    echo "✓ docker-compose.yml configured for remote OpenClaw"
fi

# Start services
echo "[5/5] Starting services..."
docker-compose up -d --build

# Wait for services to start
echo "Waiting for services to start..."
sleep 10

# Check status
echo ""
echo "============================================"
echo "Deployment Status"
echo "============================================"
docker-compose ps

echo ""
echo "============================================"
echo "TaskBridge Logs (press Ctrl+C to exit)"
echo "============================================"
docker-compose logs -f taskbridge
