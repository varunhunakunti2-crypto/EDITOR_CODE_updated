from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# Roles offered at sign-up. "admin" is deliberately excluded: the first
# account becomes admin automatically, and there is no self-service promotion.
ROLES = {
    "customer": "Customer",
    "designer": "Interior designer",
    "shop_owner": "Shop owner",
    "admin": "Admin",
}
SIGNUP_ROLES = ("customer", "designer", "shop_owner")

AVAILABILITY = {
    "in_stock": "In stock",
    "out_of_stock": "Out of stock",
    "made_to_order": "Made to order",
}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           server_default=db.func.current_timestamp())
    designs = db.relationship('Design', backref='user', lazy=True)

    def has_role(self, *roles):
        return self.role in roles

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def role_label(self):
        return ROLES.get(self.role, self.role or "Customer")

class Design(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    input_image = db.Column(db.String(200), nullable=False)
    mask_image = db.Column(db.String(200), nullable=False)
    output_image = db.Column(db.String(200), nullable=False)
    prompt = db.Column(db.String(500), nullable=False)
    position = db.Column(db.String(30), default='middle_center')
    location = db.Column(db.String(200), default='')
    places_json = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           server_default=db.func.current_timestamp())


class Product(db.Model):
    """A furniture/interior item listed by a shop owner."""
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60), default="")
    price = db.Column(db.Float, nullable=False, default=0)
    description = db.Column(db.Text, default="")
    dimensions = db.Column(db.String(60), default="")
    availability = db.Column(db.String(20), default="in_stock")
    image_file = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           server_default=db.func.current_timestamp())

    owner = db.relationship('User', backref='products', lazy=True)

    @property
    def availability_label(self):
        return AVAILABILITY.get(self.availability, self.availability or "In stock")


def upgrade_schema():
    """Add newer columns to databases created by an older version."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    design_columns = {c['name'] for c in inspector.get_columns('design')}
    wanted = {
        'position': "VARCHAR(30) DEFAULT 'middle_center'",
        'location': "VARCHAR(200) DEFAULT ''",
        'places_json': "TEXT DEFAULT ''",
    }
    with db.engine.begin() as conn:
        for name, ddl in wanted.items():
            if name not in design_columns:
                conn.execute(text(f'ALTER TABLE design ADD COLUMN {name} {ddl}'))

        # Existing accounts pre-date roles and become customers.
        user_columns = {c['name'] for c in inspector.get_columns('user')}
        if 'role' not in user_columns:
            conn.execute(text(
                "ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'customer'"
            ))
            conn.execute(text(
                "UPDATE user SET role = 'customer' WHERE role IS NULL OR role = ''"
            ))

        # An upgraded database has no admin yet: promote the earliest account.
        admins = conn.execute(text("SELECT COUNT(*) FROM user WHERE role = 'admin'")).scalar()
        if not admins:
            conn.execute(text(
                "UPDATE user SET role = 'admin' WHERE id = (SELECT MIN(id) FROM user)"
            ))

        # Older rows pre-date the created_at default: backfill any NULL timestamps
        # so templates can rely on a real date.
        for table in ('user', 'design', 'product'):
            try:
                columns = {c['name'] for c in inspector.get_columns(table)}
            except Exception:  # table not created yet on a fresh database
                continue
            if 'created_at' in columns:
                conn.execute(text(
                    f"UPDATE {table} SET created_at = CURRENT_TIMESTAMP "
                    "WHERE created_at IS NULL"
                ))
