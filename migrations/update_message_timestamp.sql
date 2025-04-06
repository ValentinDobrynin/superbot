-- Update message timestamp column to use timezone
ALTER TABLE messages 
ALTER COLUMN timestamp TYPE TIMESTAMP WITH TIME ZONE 
USING timestamp AT TIME ZONE 'UTC';

-- Update message_stats timestamp column to use timezone
ALTER TABLE message_stats 
ALTER COLUMN timestamp TYPE TIMESTAMP WITH TIME ZONE 
USING timestamp AT TIME ZONE 'UTC';

-- Update chats timestamps to use timezone
ALTER TABLE chats 
ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE 
USING created_at AT TIME ZONE 'UTC',
ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE 
USING updated_at AT TIME ZONE 'UTC',
ALTER COLUMN last_summary_timestamp TYPE TIMESTAMP WITH TIME ZONE 
USING last_summary_timestamp AT TIME ZONE 'UTC'; 