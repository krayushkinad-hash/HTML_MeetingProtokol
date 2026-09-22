-- SQL initialization for HTML_MeetingProtokol database
-- Required extensions

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE html_mp TO hmp;
GRANT ALL ON SCHEMA public TO hmp;
