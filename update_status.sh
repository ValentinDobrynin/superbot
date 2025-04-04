#!/bin/bash

echo "🔄 Starting update process..."

# 1. Execute SQL migration
echo "📊 Creating chat_stats table..."
psql $DATABASE_URL -f migrations/create_chat_stats.sql

# 2. Pull latest changes
echo "📥 Pulling latest changes from git..."
git pull origin main

# 3. Restart service
echo "🔄 Restarting service..."
sudo systemctl restart superbot

echo "✅ Update completed successfully!" 