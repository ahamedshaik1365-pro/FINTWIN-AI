"""Create the intended initial account without storing its password in source."""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.main import SessionLocal, User, password_hash


def main():
    email = input("Initial user email [shaikmasthanahamed@gmail.com]: ").strip() or "shaikmasthanahamed@gmail.com"
    name = input("Full name: ").strip()
    password = getpass.getpass("Password (hidden): ")
    if len(password) < 12:
        raise SystemExit("Use a password with at least 12 characters.")
    db = SessionLocal()
    try:
        if db.query(User).filter_by(email=email.lower()).first():
            raise SystemExit("That account already exists.")
        db.add(User(email=email.lower(), full_name=name, password_hash=password_hash.hash(password)))
        db.commit()
        print(f"Created initial account for {email}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
