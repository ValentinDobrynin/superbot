#!/bin/bash

# Get database URL from environment
DATABASE_URL=${DATABASE_URL}

# Extract connection details from URL
DB_USER=$(echo $DATABASE_URL | sed -E 's/postgresql:\/\/([^:]+):.*/\1/')
DB_PASS=$(echo $DATABASE_URL | sed -E 's/postgresql:\/\/[^:]+:([^@]+)@.*/\1/')
DB_HOST=$(echo $DATABASE_URL | sed -E 's/postgresql:\/\/[^@]+@([^:]+):.*/\1/')
DB_PORT=$(echo $DATABASE_URL | sed -E 's/postgresql:\/\/[^@]+@[^:]+:([^/]+)\/.*/\1/')
DB_NAME=$(echo $DATABASE_URL | sed -E 's/postgresql:\/\/[^@]+@[^:]+\/[^/]+\/(.+)/\1/')

# Apply migrations
echo "Applying migrations..."
alembic upgrade head

echo "Migrations applied successfully!" 