from werkzeug.security import generate_password_hash

from models import db, Product, ProductVariant, Setting, DeliveryZone
from helpers import nigerian_states_list


def seed_settings():
    defaults = {
        'site_name': ('Asequible Services Limited', 'Business name'),
        'site_tagline': ('Premium Quality Rice, Delivered to Your Door', 'Site tagline'),
        'phone': ('+234 800 000 0000', 'Business phone'),
        'whatsapp': ('+234 800 000 0000', 'WhatsApp number'),
        'email': ('info@asequible.com', 'Business email'),
        'address': ('Lagos, Nigeria', 'Business address'),
        'tax_rate': ('7.5', 'VAT rate percentage'),
        'currency': ('NGN', 'Currency code'),
        'min_order_amount': ('5000', 'Minimum order amount'),
        'paystack_public_key': ('pk_test_xxxxx', 'Paystack public key'),
        'paystack_secret_key': ('sk_test_xxxxx', 'Paystack secret key'),
        'bank_name': ('First Bank of Nigeria', 'Bank name for transfers'),
        'bank_account_number': ('0000000000', 'Bank account number'),
        'bank_account_name': ('Asequible Services Limited', 'Bank account name'),
        'admin_password': (generate_password_hash('asequible-admin-2024'), 'Admin panel password'),
        'staff_password': (generate_password_hash('asequible-staff-2024'), 'Staff panel password'),
        'whatsapp_order_message': ('Hello! I would like to place an order.', 'Default WhatsApp order message'),
        'about_text': ('Asequible Services Limited is a leading rice distributor in Nigeria, committed to delivering premium quality rice at competitive prices to both retail and wholesale customers.', 'About us text'),
        'delivery_note': ('Delivery within Lagos: 1-2 business days. Other states: 3-5 business days.', 'Delivery information'),
        'return_policy': ('Returns accepted within 24 hours of delivery if product is damaged or incorrect.', 'Return policy'),
    }
    for key, (value, desc) in defaults.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value, description=desc))
    db.session.commit()


def seed_delivery_zones():
    states = nigerian_states_list()
    lagos_fee = 2000
    nearby_states = ['Ogun', 'Oyo', 'Osun', 'Ondo', 'Ekiti', 'Kwara', 'Edo', 'Delta']
    nearby_fee = 4000
    default_fee = 6000

    for state in states:
        if not DeliveryZone.query.filter_by(state=state).first():
            if state == 'Lagos':
                fee = lagos_fee
                days = '1-2 days'
            elif state == 'FCT':
                fee = 5000
                days = '2-4 days'
            elif state in nearby_states:
                fee = nearby_fee
                days = '2-3 days'
            else:
                fee = default_fee
                days = '3-5 days'
            db.session.add(DeliveryZone(state=state, fee=fee, estimated_days=days))
    db.session.commit()


def seed_products():
    if Product.query.first():
        return

    rice = Product(
        name='Premium Nigerian Rice',
        slug='premium-nigerian-rice',
        description='Our flagship premium parboiled rice, locally sourced and processed to the highest standards. Perfect for jollof, fried rice, white rice, and all Nigerian dishes. Clean, stone-free, and consistently delicious.',
        image_url='/static/rice-hero.jpg',
        category='rice',
        is_active=True,
        is_featured=True
    )
    db.session.add(rice)
    db.session.flush()

    variants = [
        {'size': '50kg Bag', 'weight_kg': 50, 'price': 75000, 'wholesale_price': 70000, 'wholesale_min_qty': 10, 'stock': 100, 'sku': 'ASQ-RICE-50'},
        {'size': '25kg Bag', 'weight_kg': 25, 'price': 40000, 'wholesale_price': 37000, 'wholesale_min_qty': 20, 'stock': 200, 'sku': 'ASQ-RICE-25'},
        {'size': '10kg Bag', 'weight_kg': 10, 'price': 18000, 'wholesale_price': 16000, 'wholesale_min_qty': 50, 'stock': 300, 'sku': 'ASQ-RICE-10'},
        {'size': '5kg Bag', 'weight_kg': 5, 'price': 9500, 'wholesale_price': 8500, 'wholesale_min_qty': 100, 'stock': 500, 'sku': 'ASQ-RICE-05'},
    ]
    for v in variants:
        db.session.add(ProductVariant(product_id=rice.id, **v))

    db.session.commit()


def seed_all():
    seed_settings()
    seed_delivery_zones()
    seed_products()
