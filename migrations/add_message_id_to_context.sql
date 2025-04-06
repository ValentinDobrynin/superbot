-- Add message_id column to message_contexts table
ALTER TABLE message_contexts
ADD COLUMN message_id INTEGER REFERENCES messages(id);

-- Add index for better query performance
CREATE INDEX idx_message_contexts_message_id ON message_contexts(message_id); 