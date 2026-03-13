#!/bin/bash

echo "==================================="
echo "TaskBridge Docker Rebuild Script"
echo "==================================="
echo ""

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функция для вывода статуса
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Проверка наличия Docker
if ! command -v docker &> /dev/null; then
    print_error "Docker not found. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose not found. Please install Docker Compose first."
    exit 1
fi

print_status "Docker and Docker Compose found"

# Остановка контейнера
echo ""
echo "Step 1: Stopping existing containers..."
docker-compose down
print_status "Containers stopped"

# Опция для очистки кеша
echo ""
read -p "Do you want to rebuild with --no-cache? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    NO_CACHE="--no-cache"
    print_warning "Building with --no-cache (this will take longer)"
else
    NO_CACHE=""
    print_status "Building with cache"
fi

# Сборка образа
echo ""
echo "Step 2: Building Docker image..."
if docker-compose build $NO_CACHE; then
    print_status "Build completed successfully"
else
    print_error "Build failed!"
    exit 1
fi

# Запуск контейнеров
echo ""
echo "Step 3: Starting containers..."
if docker-compose up -d; then
    print_status "Containers started"
else
    print_error "Failed to start containers!"
    exit 1
fi

# Проверка что dist существует
echo ""
echo "Step 4: Verifying React build..."
sleep 3
if docker-compose exec -T web ls /app/webapp/dist/index.html &> /dev/null; then
    print_status "React build files found in container"
else
    print_warning "React build files not found! Checking logs..."
    docker-compose logs web | grep -i "dist"
fi

# Показываем логи
echo ""
echo "Step 5: Showing logs (press Ctrl+C to stop)..."
echo ""
docker-compose logs -f
