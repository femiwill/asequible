import random
import string
from datetime import datetime


def get_setting(key, default=None):
    from models import Setting
    setting = Setting.query.filter_by(key=key).first()
    return setting.value if setting else default


def format_naira(amount):
    if amount is None:
        return '₦0.00'
    return f'₦{amount:,.2f}'


def generate_order_number():
    date_part = datetime.utcnow().strftime('%y%m%d')
    rand_part = ''.join(random.choices(string.digits, k=4))
    return f'ASQ-{date_part}-{rand_part}'


def nigerian_states_list():
    return [
        'Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi', 'Bayelsa',
        'Benue', 'Borno', 'Cross River', 'Delta', 'Ebonyi', 'Edo',
        'Ekiti', 'Enugu', 'FCT', 'Gombe', 'Imo', 'Jigawa',
        'Kaduna', 'Kano', 'Katsina', 'Kebbi', 'Kogi', 'Kwara',
        'Lagos', 'Nasarawa', 'Niger', 'Ogun', 'Ondo', 'Osun',
        'Oyo', 'Plateau', 'Rivers', 'Sokoto', 'Taraba', 'Yobe', 'Zamfara'
    ]


def calculate_tax(subtotal, tax_rate=None):
    if tax_rate is None:
        rate_str = get_setting('tax_rate', '7.5')
        tax_rate = float(rate_str)
    return round(subtotal * tax_rate / 100, 2)


def get_delivery_fee(state):
    from models import DeliveryZone
    zone = DeliveryZone.query.filter_by(state=state, is_active=True).first()
    return zone.fee if zone else 0
