from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from database.models import Base
from config import settings

def check_database():
    # Create engine
    engine = create_engine(settings.DATABASE_URL)
    
    # Create session
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Get inspector
        inspector = inspect(engine)
        
        # Get all tables
        tables = inspector.get_table_names()
        print("\nTables in database:")
        for table in tables:
            print(f"\n{table}:")
            # Get columns
            columns = inspector.get_columns(table)
            for column in columns:
                print(f"  - {column['name']}: {column['type']}")
            
            # Get foreign keys
            foreign_keys = inspector.get_foreign_keys(table)
            if foreign_keys:
                print("\n  Foreign keys:")
                for fk in foreign_keys:
                    print(f"    - {fk['constrained_columns']} -> {fk['referred_table']}.{fk['referred_columns']}")
            
            # Get primary keys
            primary_keys = inspector.get_pk_constraint(table)
            if primary_keys['constrained_columns']:
                print(f"\n  Primary key: {primary_keys['constrained_columns']}")
            
            # Get check constraints
            check_constraints = inspector.get_check_constraints(table)
            if check_constraints:
                print("\n  Check constraints:")
                for constraint in check_constraints:
                    print(f"    - {constraint['name']}: {constraint['sqltext']}")
    finally:
        session.close()

if __name__ == "__main__":
    check_database() 