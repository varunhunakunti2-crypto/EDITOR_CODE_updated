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

ENQUIRY_KINDS = {"enquiry": "Enquiry", "order": "Order"}
ENQUIRY_STATUSES = {"new": "New", "responded": "Responded", "closed": "Closed"}


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

    # Room details captured before generation (all optional for older rows).
    room_type = db.Column(db.String(60), default='', server_default='')
    style = db.Column(db.String(60), default='', server_default='')
    budget = db.Column(db.String(80), default='', server_default='')
    preferences = db.Column(db.Text, default='', server_default='')
    width_m = db.Column(db.Float)
    length_m = db.Column(db.Float)
    height_m = db.Column(db.Float)
    detection_notes = db.Column(db.Text, default='', server_default='')
    placement_json = db.Column(db.Text, default='', server_default='')

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


class ShopProfile(db.Model):
    """Business details submitted by a shop owner (one profile per owner)."""
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False,
                         unique=True, index=True)
    shop_name = db.Column(db.String(120), nullable=False, default='')
    city = db.Column(db.String(100), default='')
    address = db.Column(db.Text, default='')
    phone = db.Column(db.String(40), default='')
    verified = db.Column(db.Boolean, default=False, server_default='0')
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow,
                             server_default=db.func.current_timestamp())

    owner = db.relationship('User', backref=db.backref('shop_profile', uselist=False))


class Enquiry(db.Model):
    """A message from a customer to a shop owner about a product or design."""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'),
                           nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'),
                            nullable=False, index=True)
    shop_owner_id = db.Column(db.Integer, db.ForeignKey('user.id'),
                              nullable=False, index=True)
    design_id = db.Column(db.Integer, db.ForeignKey('design.id'), index=True)
    message = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='new', server_default='new')
    kind = db.Column(db.String(20), default='enquiry', server_default='enquiry')
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           server_default=db.func.current_timestamp())

    product = db.relationship('Product', backref='enquiries')
    design = db.relationship('Design', backref='enquiries')
    customer = db.relationship('User', foreign_keys=[customer_id],
                               backref='sent_enquiries')
    shop_owner = db.relationship('User', foreign_keys=[shop_owner_id],
                                 backref='received_enquiries')

    @property
    def kind_label(self):
        return ENQUIRY_KINDS.get(self.kind, self.kind or "Enquiry")

    @property
    def status_label(self):
        return ENQUIRY_STATUSES.get(self.status, self.status or "New")


def upgrade_schema():
    """Add newer columns to databases created by an older version."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    design_columns = {c['name'] for c in inspector.get_columns('design')}
    wanted = {
        'position': "VARCHAR(30) DEFAULT 'middle_center'",
        'location': "VARCHAR(200) DEFAULT ''",
        'places_json': "TEXT DEFAULT ''",
        'room_type': "VARCHAR(60) DEFAULT ''",
        'style': "VARCHAR(60) DEFAULT ''",
        'budget': "VARCHAR(80) DEFAULT ''",
        'preferences': "TEXT DEFAULT ''",
        'width_m': "FLOAT",
        'length_m': "FLOAT",
        'height_m': "FLOAT",
        'detection_notes': "TEXT DEFAULT ''",
        'placement_json': "TEXT DEFAULT ''",
    }
    with db.engine.begin() as conn:
        for name, ddl in wanted.items():
            if name not in design_columns:
                conn.execute(text(f'ALTER TABLE design ADD COLUMN {name} {ddl}'))

        # create_all() normally does this, but keep upgrades self-contained so
        # an existing database gains the new tables without touching old rows.
        ShopProfile.__table__.create(bind=conn, checkfirst=True)
        Enquiry.__table__.create(bind=conn, checkfirst=True)

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

        # Shops that existed before verification was introduced stay visible:
        # give each one an approved profile. New shops start unverified.
        legacy_shops = conn.execute(text(
            "SELECT id, username FROM user WHERE role = 'shop_owner'"
        )).all()
        for owner_id, username in legacy_shops:
            has_profile = conn.execute(text(
                "SELECT 1 FROM shop_profile WHERE owner_id = :owner"
            ), {'owner': owner_id}).first()
            if not has_profile:
                conn.execute(text(
                    "INSERT INTO shop_profile (owner_id, shop_name, verified, "
                    "submitted_at) VALUES (:owner, :name, 1, CURRENT_TIMESTAMP)"
                ), {'owner': owner_id, 'name': (username or 'Shop') + ' Shop'})

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
