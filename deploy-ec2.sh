#!/bin/bash

# EC2 Job Monitoring Deployment Script
set -e

echo "🚀 Starting Job Monitoring deployment on EC2..."

# Update system
sudo apt-get update -y

# Install Docker
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    sudo apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io
    sudo usermod -aG docker $USER
fi

# Install Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo curl -L "https://github.com/docker/compose/releases/download/v2.21.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

# Create application directory
APP_DIR="/opt/job-monitoring"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# Clone or copy application files
if [ ! -d "$APP_DIR/.git" ]; then
    echo "Setting up application files..."
    # Copy current directory to APP_DIR
    sudo cp -r . $APP_DIR/
    sudo chown -R $USER:$USER $APP_DIR
fi

cd $APP_DIR

# Create environment file from template
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cat > .env << EOF
AIRFLOW_UID=50000
GOOGLE_SHEET_KEY=\${GOOGLE_SHEET_KEY}
SLACK_WEBHOOK_URL=\${SLACK_WEBHOOK_URL}
TOP5000COMPANY_URL=\${TOP5000COMPANY_URL}
EOF
    echo "⚠️  Please update .env file with your actual values"
fi

# Create directories for volumes
mkdir -p logs plugins data key

# Build and start services
echo "Building and starting services..."
docker-compose build
docker-compose up -d

# Wait for services to be healthy
echo "Waiting for services to start..."
sleep 30

# Check service status
docker-compose ps

echo "✅ Deployment completed!"
echo "🌐 Airflow UI: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8080"
echo "📊 Check logs: docker-compose logs -f"
echo "🔧 Stop services: docker-compose down"