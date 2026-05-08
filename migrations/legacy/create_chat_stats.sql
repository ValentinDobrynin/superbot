-- Check if table exists
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'chat_stats') THEN
        -- Create the table if it doesn't exist
        CREATE TABLE chat_stats (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            message_count INTEGER NOT NULL,
            user_count INTEGER NOT NULL,
            avg_length FLOAT NOT NULL,
            emoji_count INTEGER NOT NULL,
            sticker_count INTEGER NOT NULL,
            top_emojis JSONB NOT NULL,
            top_stickers JSONB NOT NULL,
            top_words JSONB NOT NULL,
            top_topics JSONB NOT NULL,
            most_active_hour INTEGER,
            most_active_day VARCHAR(20),
            activity_trend JSONB NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            UNIQUE(chat_id)
        );
        RAISE NOTICE 'Table chat_stats created successfully';
    ELSE
        RAISE NOTICE 'Table chat_stats already exists';
    END IF;
END $$; 