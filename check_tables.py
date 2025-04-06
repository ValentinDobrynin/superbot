from sqlalchemy import create_engine, text
from src.config import settings

engine = create_engine(settings.DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute(text('SELECT table_name FROM information_schema.tables WHERE table_schema = \'public\''))
    print('\nTables in database:')
    for row in result:
        print(row[0]) 