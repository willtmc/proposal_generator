from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Text, JSON
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.exc import SQLAlchemyError
import os
from pathlib import Path # Import Path

# --- Database URL Configuration ---
# Check if running in Railway environment
RAILWAY_VOLUME_PATH = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")

if RAILWAY_VOLUME_PATH:
    # Use the persistent volume path provided by Railway
    # Ensure the directory exists
    db_dir = Path(RAILWAY_VOLUME_PATH)
    db_dir.mkdir(parents=True, exist_ok=True)
    DATABASE_FILE = db_dir / "proposals.db"
    DATABASE_URL = f"sqlite:///{DATABASE_FILE.resolve()}"
    print(f"Using Railway volume for database: {DATABASE_URL}")
else:
    # Default local path (relative to where the script is run)
    # This will typically be the project root when run locally or in basic Docker
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./proposals.db")
    print(f"Using local path for database: {DATABASE_URL}")

# Use connect_args for SQLite only to ensure thread safety
engine_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=engine_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# --- Database Models ---

class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False, unique=True)
    # Relationship to link proposal data entries
    data_entries = relationship("ProposalData", back_populates="proposal", cascade="all, delete-orphan")

class ProposalData(Base):
    __tablename__ = "proposal_data"

    id = Column(Integer, primary_key=True, index=True)
    proposal_id = Column(Integer, ForeignKey("proposals.id"), nullable=False)
    key = Column(String, nullable=False)
    # Store value as TEXT, assuming various data types might be needed.
    # Consider JSON type if values are consistently structured dictionaries/lists.
    value = Column(Text, nullable=True) # Or use JSON type: value = Column(JSON, nullable=True)

    proposal = relationship("Proposal", back_populates="data_entries")


# --- Database Initialization ---

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    try:
        # Ensure the directory for the database file exists (especially for local runs)
        if DATABASE_URL.startswith("sqlite"):
             db_path = Path(DATABASE_URL.split("///")[1])
             db_path.parent.mkdir(parents=True, exist_ok=True)

        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully.")
    except SQLAlchemyError as e:
        print(f"Error creating database tables: {e}")
        # Depending on the application, you might want to raise the exception
        # raise

# --- CRUD Functions ---

def get_db():
    """Dependency to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_proposal(db, proposal_name: str) -> Proposal:
    """Creates a new proposal entry."""
    try:
        db_proposal = Proposal(name=proposal_name)
        db.add(db_proposal)
        db.commit()
        db.refresh(db_proposal)
        print(f"Proposal '{proposal_name}' created with ID: {db_proposal.id}")
        return db_proposal
    except SQLAlchemyError as e:
        db.rollback()
        print(f"Error creating proposal '{proposal_name}': {e}")
        raise  # Re-raise the exception for the caller to handle

def add_proposal_data(db, proposal_id: int, data_dict: dict) -> list[ProposalData]:
    """Adds key-value pairs from a dictionary to a specific proposal."""
    new_entries = []
    try:
        # Fetch the proposal first to ensure it exists
        proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
        if not proposal:
            raise ValueError(f"Proposal with ID {proposal_id} not found.")

        for key, value in data_dict.items():
            # Convert non-string values simply to string for TEXT column
            # If using JSON column, ensure value is JSON serializable
            str_value = str(value) if value is not None else None
            db_data = ProposalData(proposal_id=proposal_id, key=key, value=str_value)
            db.add(db_data)
            new_entries.append(db_data)

        db.commit()
        # Refresh each new entry to get generated IDs, etc.
        for entry in new_entries:
             db.refresh(entry)
        print(f"Added {len(new_entries)} data entries for proposal ID: {proposal_id}")
        return new_entries
    except SQLAlchemyError as e:
        db.rollback()
        print(f"Error adding data for proposal ID {proposal_id}: {e}")
        raise # Re-raise
    except ValueError as e:
        db.rollback()
        print(e)
        raise # Re-raise

def get_proposal_with_data(db, proposal_id: int) -> Proposal | None:
    """Retrieves a proposal and all its associated key-value data."""
    try:
        # Use joinedload for efficient loading of related data
        from sqlalchemy.orm import joinedload
        proposal = db.query(Proposal).options(joinedload(Proposal.data_entries)).filter(Proposal.id == proposal_id).first()
        if proposal:
            print(f"Retrieved proposal ID: {proposal_id} with {len(proposal.data_entries)} data entries.")
        else:
            print(f"Proposal ID: {proposal_id} not found.")
        return proposal
    except SQLAlchemyError as e:
        print(f"Error retrieving proposal ID {proposal_id}: {e}")
        raise # Re-raise

# Example Usage (Optional - can be run directly for testing)
if __name__ == "__main__":
    print("Initializing DB for direct script run...")
    init_db()

    # Example: Create a proposal and add data
    db_session = next(get_db())
    try:
        # Ensure proposal doesn't exist before creating
        existing_proposal = db_session.query(Proposal).filter(Proposal.name == "Test Proposal 1").first()
        if not existing_proposal:
             new_proposal = create_proposal(db_session, "Test Proposal 1")
             if new_proposal:
                 data_to_add = {"client_name": "Acme Corp", "project_scope": "Develop a new widget", "budget": 10000}
                 added_data = add_proposal_data(db_session, new_proposal.id, data_to_add)
                 # Retrieve and print
                 retrieved_proposal = get_proposal_with_data(db_session, new_proposal.id)
                 if retrieved_proposal:
                     print(f"\nRetrieved Proposal: {retrieved_proposal.name}")
                     for item in retrieved_proposal.data_entries:
                         print(f"  Key: {item.key}, Value: {item.value}")
        else:
            print("'Test Proposal 1' already exists.")
            # Optionally retrieve existing proposal
            retrieved_proposal = get_proposal_with_data(db_session, existing_proposal.id)
            if retrieved_proposal:
                 print(f"\nExisting Proposal: {retrieved_proposal.name}")
                 for item in retrieved_proposal.data_entries:
                     print(f"  Key: {item.key}, Value: {item.value}")


    except Exception as e:
        print(f"An error occurred during example usage: {e}")
    finally:
        db_session.close() 