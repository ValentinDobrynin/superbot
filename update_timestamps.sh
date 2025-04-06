#!/bin/bash

# Load environment variables
source .env

# Apply migration
psql $DATABASE_URL -f migrations/update_message_timestamp.sql

echo "Migration completed successfully" 