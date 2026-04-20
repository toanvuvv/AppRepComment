from app.database import Base, engine, SessionLocal
from app.models.user import User


def test_user_model_persists():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        u = User(
            username="alice_test_model",
            password_hash="x",
            role="user",
            max_nicks=5,
            is_locked=False,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        assert u.id is not None
        assert u.username == "alice_test_model"
        assert u.max_nicks == 5
        db.delete(u)
        db.commit()
