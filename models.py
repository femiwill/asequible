from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    category = db.Column(db.String(100), default='rice')
    is_active = db.Column(db.Boolean, default=True)
    is_featured = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    variants = db.relationship('ProductVariant', backref='product', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Product {self.name}>'

    @property
    def min_price(self):
        active = [v for v in self.variants if v.is_active]
        return min((v.price for v in active), default=0)

    @property
    def max_price(self):
        active = [v for v in self.variants if v.is_active]
        return max((v.price for v in active), default=0)


class ProductVariant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    size = db.Column(db.String(50), nullable=False)
    weight_kg = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)
    wholesale_price = db.Column(db.Float)
    wholesale_min_qty = db.Column(db.Integer, default=10)
    stock = db.Column(db.Integer, default=0)
    sku = db.Column(db.String(50), unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Variant {self.size} - ₦{self.price}>'

    @property
    def in_stock(self):
        return self.stock > 0


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200))
    phone = db.Column(db.String(20), nullable=True)
    customer_type = db.Column(db.String(20), default='retail')  # retail or wholesale
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    notes = db.Column(db.Text)
    password_hash = db.Column(db.String(256))
    google_id = db.Column(db.String(100), unique=True)
    is_registered = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    orders = db.relationship('Order', backref='customer', lazy=True)

    def __repr__(self):
        return f'<Customer {self.name}>'

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, pw)

    @property
    def total_spent(self):
        return sum(o.total for o in self.orders if o.status != 'cancelled')

    @property
    def order_count(self):
        return len([o for o in self.orders if o.status != 'cancelled'])


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    delivery_name = db.Column(db.String(200))
    delivery_phone = db.Column(db.String(20))
    delivery_address = db.Column(db.Text, nullable=False)
    delivery_city = db.Column(db.String(100))
    delivery_state = db.Column(db.String(100))
    subtotal = db.Column(db.Float, default=0)
    tax_amount = db.Column(db.Float, default=0)
    delivery_fee = db.Column(db.Float, default=0)
    discount = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, processing, shipped, delivered, cancelled
    payment_method = db.Column(db.String(20))  # paystack, bank_transfer, cash_on_delivery
    payment_status = db.Column(db.String(20), default='unpaid')  # unpaid, paid, partial, refunded
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='order', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Order {self.order_number}>'


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    variant_size = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    line_total = db.Column(db.Float, nullable=False)

    variant = db.relationship('ProductVariant')

    def __repr__(self):
        return f'<OrderItem {self.product_name} x{self.quantity}>'


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    method = db.Column(db.String(20), nullable=False)  # paystack, bank_transfer, cash_on_delivery
    amount = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(200))
    paystack_ref = db.Column(db.String(200))
    status = db.Column(db.String(20), default='pending')  # pending, success, failed
    verified_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Payment {self.method} ₦{self.amount}>'


class InventoryLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # restock, sale, adjustment, return
    quantity_change = db.Column(db.Integer, nullable=False)
    stock_before = db.Column(db.Integer, nullable=False)
    stock_after = db.Column(db.Integer, nullable=False)
    reference = db.Column(db.String(200))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    variant = db.relationship('ProductVariant')

    def __repr__(self):
        return f'<InventoryLog {self.action} {self.quantity_change}>'


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.String(200))

    def __repr__(self):
        return f'<Setting {self.key}={self.value}>'


class DeliveryZone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(100), unique=True, nullable=False)
    fee = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)
    estimated_days = db.Column(db.String(20), default='3-5 days')

    def __repr__(self):
        return f'<DeliveryZone {self.state} ₦{self.fee}>'
