-- Drop existing foreign key if exists
ALTER TABLE message_contexts
DROP CONSTRAINT IF EXISTS message_contexts_message_id_fkey;

-- Add foreign key constraint
ALTER TABLE message_contexts
ADD CONSTRAINT message_contexts_message_id_fkey
FOREIGN KEY (message_id)
REFERENCES messages(id)
ON DELETE CASCADE; 