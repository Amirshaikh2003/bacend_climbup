-- ClimbUP: Allow uncategorized uploads from WhatsApp
-- Run this in Supabase SQL Editor

-- Step 1: Remove NOT NULL constraint from subject_id
ALTER TABLE student_resources 
ALTER COLUMN subject_id DROP NOT NULL;

-- Step 2: Verify the change
SELECT column_name, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'student_resources' 
AND column_name = 'subject_id';
