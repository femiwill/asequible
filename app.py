import os
import json
import hmac
import hashlib
import csv
import io
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, jsonify, abort, make_response, Response
)
from flask_sqlalchemy import SQLAlchemy
import requests

from models import db, Product, ProductVariant, Customer, Order, OrderItem, Payment, InventoryLog, Setting, DeliveryZone
from helpers import get_setting, format_naira, generate_order_number, nigerian_states_list, calculate_tax, get_delivery_fee
from seed_data import seed_all

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'asequible-dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///asequible.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()
    seed_all()


# ─── Template Filters ───────────────────────────────────────────────
@app.template_filter('naira')
def naira_filter(value):
    return format_naira(value)


@app.context_processor
def inject_globals():
    cart = session.get('cart', {})
    cart_count = sum(item['qty'] for item in cart.values())
    current_user = None
    customer_id = session.get('customer_id')
    if customer_id:
        current_user = Customer.query.get(customer_id)
        if current_user and not current_user.is_registered:
            current_user = None
            session.pop('customer_id', None)
    return {
        'site_name': get_setting('site_name', 'Asequible Services Limited'),
        'site_tagline': get_setting('site_tagline', 'Premium Quality Rice'),
        'whatsapp': get_setting('whatsapp', '+234 800 000 0000'),
        'phone': get_setting('phone', '+234 800 000 0000'),
        'site_email': get_setting('email', 'info@asequible.com'),
        'cart_count': cart_count,
        'nigerian_states': nigerian_states_list(),
        'current_year': datetime.utcnow().year,
        'current_user': current_user,
    }


# ─── Admin Auth ──────────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        admin_pw = get_setting('admin_password', 'asequible-admin-2024')
        if password == admin_pw:
            session['admin_logged_in'] = True
            flash('Welcome to the admin panel!', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Invalid password.', 'danger')
    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out.', 'info')
    return redirect(url_for('admin_login'))


# ─── Customer Auth ───────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        customer_id = session.get('customer_id')
        if not customer_id:
            flash('Please log in to access your account.', 'warning')
            return redirect(url_for('login', next=request.path))
        customer = Customer.query.get(customer_id)
        if not customer or not customer.is_registered:
            session.pop('customer_id', None)
            flash('Please log in to access your account.', 'warning')
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated


@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('customer_id'):
        customer = Customer.query.get(session['customer_id'])
        if customer and customer.is_registered:
            return redirect(url_for('account'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not all([name, phone, password]):
            flash('Name, phone, and password are required.', 'danger')
            return render_template('auth/register.html')

        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('auth/register.html')

        existing = Customer.query.filter_by(phone=phone, is_registered=True).first()
        if existing:
            flash('An account with this phone number already exists. Please log in.', 'warning')
            return redirect(url_for('login'))

        if email:
            existing_email = Customer.query.filter_by(email=email, is_registered=True).first()
            if existing_email:
                flash('An account with this email already exists. Please log in.', 'warning')
                return redirect(url_for('login'))

        customer = Customer.query.filter_by(phone=phone).first()
        if customer:
            customer.name = name
            if email:
                customer.email = email
        else:
            customer = Customer(name=name, phone=phone, email=email)
            db.session.add(customer)

        customer.set_password(password)
        customer.is_registered = True
        db.session.commit()

        session['customer_id'] = customer.id
        flash('Account created! Welcome to Asequible.', 'success')
        return redirect(url_for('account'))

    return render_template('auth/register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('customer_id'):
        customer = Customer.query.get(session['customer_id'])
        if customer and customer.is_registered:
            return redirect(url_for('account'))

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')

        if not identifier or not password:
            flash('Please enter your phone/email and password.', 'danger')
            return render_template('auth/login.html')

        customer = Customer.query.filter(
            db.or_(Customer.phone == identifier, Customer.email == identifier),
            Customer.is_registered == True
        ).first()

        if customer and customer.check_password(password):
            session['customer_id'] = customer.id
            flash(f'Welcome back, {customer.name}!', 'success')
            next_page = request.args.get('next') or request.form.get('next') or url_for('account')
            return redirect(next_page)

        flash('Invalid phone/email or password.', 'danger')
        return render_template('auth/login.html')

    return render_template('auth/login.html')


@app.route('/logout')
def logout():
    session.pop('customer_id', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/account')
@login_required
def account():
    customer = Customer.query.get(session['customer_id'])
    recent_orders = Order.query.filter_by(customer_id=customer.id).order_by(Order.created_at.desc()).limit(5).all()
    return render_template('account/dashboard.html', customer=customer, recent_orders=recent_orders)


@app.route('/account/orders')
@login_required
def account_orders():
    customer = Customer.query.get(session['customer_id'])
    orders = Order.query.filter_by(customer_id=customer.id).order_by(Order.created_at.desc()).all()
    return render_template('account/orders.html', customer=customer, orders=orders)


@app.route('/create-account', methods=['POST'])
def create_account_post_checkout():
    """Handle post-checkout account creation (just password, customer already exists)."""
    customer_id = request.form.get('customer_id', type=int)
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')

    if not customer_id or not password:
        flash('Something went wrong. Please try again.', 'danger')
        return redirect(url_for('index'))

    if password != confirm:
        flash('Passwords do not match.', 'danger')
        return redirect(request.referrer or url_for('index'))

    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(request.referrer or url_for('index'))

    customer = Customer.query.get(customer_id)
    if not customer:
        flash('Customer not found.', 'danger')
        return redirect(url_for('index'))

    if customer.is_registered:
        flash('This account is already registered. Please log in.', 'info')
        return redirect(url_for('login'))

    existing = Customer.query.filter(
        Customer.phone == customer.phone, Customer.is_registered == True, Customer.id != customer.id
    ).first()
    if existing:
        flash('An account with this phone number already exists. Please log in.', 'warning')
        return redirect(url_for('login'))

    customer.set_password(password)
    customer.is_registered = True
    db.session.commit()

    session['customer_id'] = customer.id
    flash('Account created! You can now track your orders and enjoy faster checkout.', 'success')
    return redirect(url_for('account'))


# ─── Admin Dashboard ────────────────────────────────────────────────
@app.route('/admin')
@admin_required
def admin_dashboard():
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    month_start = today.replace(day=1)

    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    today_orders = Order.query.filter(db.func.date(Order.created_at) == today).count()

    total_revenue = db.session.query(db.func.sum(Order.total)).filter(
        Order.payment_status == 'paid', Order.status != 'cancelled'
    ).scalar() or 0

    month_revenue = db.session.query(db.func.sum(Order.total)).filter(
        Order.payment_status == 'paid', Order.status != 'cancelled',
        Order.created_at >= datetime.combine(month_start, datetime.min.time())
    ).scalar() or 0

    total_customers = Customer.query.count()
    low_stock = ProductVariant.query.filter(ProductVariant.stock < 20, ProductVariant.is_active == True).all()

    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()

    return render_template('admin/dashboard.html',
        total_orders=total_orders, pending_orders=pending_orders,
        today_orders=today_orders, total_revenue=total_revenue,
        month_revenue=month_revenue, total_customers=total_customers,
        low_stock=low_stock, recent_orders=recent_orders)


# ─── Admin Products ─────────────────────────────────────────────────
@app.route('/admin/products')
@admin_required
def admin_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template('admin/products.html', products=products)


@app.route('/admin/products/new', methods=['GET', 'POST'])
@admin_required
def admin_product_new():
    if request.method == 'POST':
        name = request.form['name']
        slug = request.form.get('slug', '').strip() or name.lower().replace(' ', '-')
        product = Product(
            name=name, slug=slug,
            description=request.form.get('description', ''),
            image_url=request.form.get('image_url', ''),
            category=request.form.get('category', 'rice'),
            is_active='is_active' in request.form,
            is_featured='is_featured' in request.form
        )
        db.session.add(product)
        db.session.flush()

        sizes = request.form.getlist('variant_size')
        weights = request.form.getlist('variant_weight')
        prices = request.form.getlist('variant_price')
        w_prices = request.form.getlist('variant_wholesale_price')
        w_qtys = request.form.getlist('variant_wholesale_qty')
        stocks = request.form.getlist('variant_stock')
        skus = request.form.getlist('variant_sku')

        for i in range(len(sizes)):
            if sizes[i].strip():
                variant = ProductVariant(
                    product_id=product.id,
                    size=sizes[i],
                    weight_kg=float(weights[i] or 0),
                    price=float(prices[i] or 0),
                    wholesale_price=float(w_prices[i] or 0) if i < len(w_prices) and w_prices[i] else None,
                    wholesale_min_qty=int(w_qtys[i] or 10) if i < len(w_qtys) and w_qtys[i] else 10,
                    stock=int(stocks[i] or 0),
                    sku=skus[i] if i < len(skus) and skus[i] else None,
                    is_active=True
                )
                db.session.add(variant)

        db.session.commit()
        flash('Product created!', 'success')
        return redirect(url_for('admin_products'))

    return render_template('admin/product_edit.html', product=None)


@app.route('/admin/products/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_product_edit(id):
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        product.name = request.form['name']
        product.slug = request.form.get('slug', '').strip() or product.name.lower().replace(' ', '-')
        product.description = request.form.get('description', '')
        product.image_url = request.form.get('image_url', '')
        product.category = request.form.get('category', 'rice')
        product.is_active = 'is_active' in request.form
        product.is_featured = 'is_featured' in request.form

        existing_ids = request.form.getlist('variant_id')
        sizes = request.form.getlist('variant_size')
        weights = request.form.getlist('variant_weight')
        prices = request.form.getlist('variant_price')
        w_prices = request.form.getlist('variant_wholesale_price')
        w_qtys = request.form.getlist('variant_wholesale_qty')
        stocks = request.form.getlist('variant_stock')
        skus = request.form.getlist('variant_sku')
        active_flags = request.form.getlist('variant_active')

        keep_ids = set()
        for i in range(len(sizes)):
            if not sizes[i].strip():
                continue
            vid = int(existing_ids[i]) if i < len(existing_ids) and existing_ids[i] else 0
            if vid:
                variant = ProductVariant.query.get(vid)
                if variant:
                    variant.size = sizes[i]
                    variant.weight_kg = float(weights[i] or 0)
                    variant.price = float(prices[i] or 0)
                    variant.wholesale_price = float(w_prices[i] or 0) if i < len(w_prices) and w_prices[i] else None
                    variant.wholesale_min_qty = int(w_qtys[i] or 10) if i < len(w_qtys) and w_qtys[i] else 10
                    variant.stock = int(stocks[i] or 0)
                    variant.sku = skus[i] if i < len(skus) and skus[i] else None
                    variant.is_active = str(i) in active_flags
                    keep_ids.add(vid)
            else:
                variant = ProductVariant(
                    product_id=product.id, size=sizes[i],
                    weight_kg=float(weights[i] or 0), price=float(prices[i] or 0),
                    wholesale_price=float(w_prices[i] or 0) if i < len(w_prices) and w_prices[i] else None,
                    wholesale_min_qty=int(w_qtys[i] or 10) if i < len(w_qtys) and w_qtys[i] else 10,
                    stock=int(stocks[i] or 0),
                    sku=skus[i] if i < len(skus) and skus[i] else None,
                    is_active=str(i) in active_flags
                )
                db.session.add(variant)

        db.session.commit()
        flash('Product updated!', 'success')
        return redirect(url_for('admin_products'))

    return render_template('admin/product_edit.html', product=product)


@app.route('/admin/products/<int:id>/delete', methods=['POST'])
@admin_required
def admin_product_delete(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'info')
    return redirect(url_for('admin_products'))


# ─── Admin Orders ────────────────────────────────────────────────────
@app.route('/admin/orders')
@admin_required
def admin_orders():
    status_filter = request.args.get('status', '')
    query = Order.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    orders = query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=orders, status_filter=status_filter)


@app.route('/admin/orders/<int:id>')
@admin_required
def admin_order_detail(id):
    order = Order.query.get_or_404(id)
    return render_template('admin/order_detail.html', order=order)


@app.route('/admin/orders/<int:id>/update-status', methods=['POST'])
@admin_required
def admin_order_update_status(id):
    order = Order.query.get_or_404(id)
    new_status = request.form.get('status')
    if new_status:
        order.status = new_status
        db.session.commit()
        flash(f'Order status updated to {new_status}.', 'success')
    return redirect(url_for('admin_order_detail', id=id))


@app.route('/admin/orders/<int:id>/confirm-payment', methods=['POST'])
@admin_required
def admin_confirm_payment(id):
    order = Order.query.get_or_404(id)
    order.payment_status = 'paid'
    payment = Payment(
        order_id=order.id, method=order.payment_method or 'bank_transfer',
        amount=order.total, status='success',
        reference=request.form.get('reference', ''),
        notes=request.form.get('notes', 'Manually confirmed by admin'),
        verified_at=datetime.utcnow()
    )
    db.session.add(payment)
    if order.status == 'pending':
        order.status = 'confirmed'
    db.session.commit()
    flash('Payment confirmed!', 'success')
    return redirect(url_for('admin_order_detail', id=id))


# ─── Admin Customers ────────────────────────────────────────────────
@app.route('/admin/customers')
@admin_required
def admin_customers():
    customers = Customer.query.order_by(Customer.created_at.desc()).all()
    return render_template('admin/customers.html', customers=customers)


@app.route('/admin/customers/<int:id>')
@admin_required
def admin_customer_detail(id):
    customer = Customer.query.get_or_404(id)
    return render_template('admin/customer_detail.html', customer=customer)


# ─── Admin Inventory ────────────────────────────────────────────────
@app.route('/admin/inventory')
@admin_required
def admin_inventory():
    variants = ProductVariant.query.join(Product).order_by(Product.name, ProductVariant.weight_kg.desc()).all()
    return render_template('admin/inventory.html', variants=variants)


@app.route('/admin/inventory/<int:variant_id>/restock', methods=['POST'])
@admin_required
def admin_restock(variant_id):
    variant = ProductVariant.query.get_or_404(variant_id)
    qty = int(request.form.get('quantity', 0))
    if qty > 0:
        stock_before = variant.stock
        variant.stock += qty
        log = InventoryLog(
            variant_id=variant.id, action='restock',
            quantity_change=qty, stock_before=stock_before,
            stock_after=variant.stock, notes=request.form.get('notes', '')
        )
        db.session.add(log)
        db.session.commit()
        flash(f'Restocked {qty} units.', 'success')
    return redirect(url_for('admin_inventory'))


@app.route('/admin/inventory/log')
@admin_required
def admin_inventory_log():
    logs = InventoryLog.query.order_by(InventoryLog.created_at.desc()).limit(200).all()
    return render_template('admin/inventory_log.html', logs=logs)


# ─── Admin Reports ──────────────────────────────────────────────────
@app.route('/admin/reports/sales')
@admin_required
def admin_report_sales():
    period = request.args.get('period', '30')
    days = int(period)
    start_date = datetime.utcnow() - timedelta(days=days)

    orders = Order.query.filter(
        Order.created_at >= start_date, Order.status != 'cancelled'
    ).order_by(Order.created_at).all()

    total_revenue = sum(o.total for o in orders if o.payment_status == 'paid')
    total_orders = len(orders)
    paid_orders = len([o for o in orders if o.payment_status == 'paid'])

    daily_data = {}
    for o in orders:
        day = o.created_at.strftime('%Y-%m-%d')
        if day not in daily_data:
            daily_data[day] = {'revenue': 0, 'orders': 0}
        if o.payment_status == 'paid':
            daily_data[day]['revenue'] += o.total
        daily_data[day]['orders'] += 1

    item_sales = {}
    for o in orders:
        for item in o.items:
            key = f'{item.product_name} ({item.variant_size})'
            if key not in item_sales:
                item_sales[key] = {'qty': 0, 'revenue': 0}
            item_sales[key]['qty'] += item.quantity
            item_sales[key]['revenue'] += item.line_total

    best_sellers = sorted(item_sales.items(), key=lambda x: x[1]['revenue'], reverse=True)[:10]

    payment_breakdown = {}
    for o in orders:
        method = o.payment_method or 'unknown'
        if method not in payment_breakdown:
            payment_breakdown[method] = {'count': 0, 'total': 0}
        payment_breakdown[method]['count'] += 1
        if o.payment_status == 'paid':
            payment_breakdown[method]['total'] += o.total

    return render_template('admin/report_sales.html',
        period=period, total_revenue=total_revenue,
        total_orders=total_orders, paid_orders=paid_orders,
        daily_data=json.dumps(daily_data), best_sellers=best_sellers,
        payment_breakdown=payment_breakdown)


@app.route('/admin/reports/tax')
@admin_required
def admin_report_tax():
    year = request.args.get('year', str(datetime.utcnow().year))
    orders = Order.query.filter(
        db.func.strftime('%Y', Order.created_at) == year,
        Order.payment_status == 'paid', Order.status != 'cancelled'
    ).order_by(Order.created_at).all()

    monthly = {}
    for o in orders:
        month = o.created_at.strftime('%Y-%m')
        if month not in monthly:
            monthly[month] = {'subtotal': 0, 'tax': 0, 'total': 0, 'orders': 0}
        monthly[month]['subtotal'] += o.subtotal
        monthly[month]['tax'] += o.tax_amount
        monthly[month]['total'] += o.total
        monthly[month]['orders'] += 1

    total_tax = sum(m['tax'] for m in monthly.values())
    total_subtotal = sum(m['subtotal'] for m in monthly.values())

    return render_template('admin/report_tax.html',
        year=year, monthly=monthly, total_tax=total_tax, total_subtotal=total_subtotal)


@app.route('/admin/reports/tax/export')
@admin_required
def admin_tax_export():
    year = request.args.get('year', str(datetime.utcnow().year))
    orders = Order.query.filter(
        db.func.strftime('%Y', Order.created_at) == year,
        Order.payment_status == 'paid', Order.status != 'cancelled'
    ).order_by(Order.created_at).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Order Number', 'Date', 'Customer', 'Subtotal', 'Tax', 'Total'])
    for o in orders:
        writer.writerow([o.order_number, o.created_at.strftime('%Y-%m-%d'),
                        o.customer.name, o.subtotal, o.tax_amount, o.total])

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = f'attachment; filename=tax_report_{year}.csv'
    return resp


# ─── Admin Settings ─────────────────────────────────────────────────
@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        for key in request.form:
            if key.startswith('setting_'):
                setting_key = key[8:]
                setting = Setting.query.filter_by(key=setting_key).first()
                if setting:
                    setting.value = request.form[key]
                else:
                    db.session.add(Setting(key=setting_key, value=request.form[key]))
        db.session.commit()
        flash('Settings saved!', 'success')
        return redirect(url_for('admin_settings'))

    settings = Setting.query.order_by(Setting.key).all()
    delivery_zones = DeliveryZone.query.order_by(DeliveryZone.state).all()
    return render_template('admin/settings.html', settings=settings, delivery_zones=delivery_zones)


@app.route('/admin/settings/delivery-zones', methods=['POST'])
@admin_required
def admin_update_delivery_zones():
    for zone in DeliveryZone.query.all():
        fee_key = f'fee_{zone.id}'
        days_key = f'days_{zone.id}'
        active_key = f'active_{zone.id}'
        if fee_key in request.form:
            zone.fee = float(request.form[fee_key] or 0)
        if days_key in request.form:
            zone.estimated_days = request.form[days_key]
        zone.is_active = active_key in request.form
    db.session.commit()
    flash('Delivery zones updated!', 'success')
    return redirect(url_for('admin_settings'))


# ─── Public: Homepage ────────────────────────────────────────────────
@app.route('/')
def index():
    featured = Product.query.filter_by(is_active=True, is_featured=True).all()
    products = Product.query.filter_by(is_active=True).all()
    return render_template('index.html', featured=featured, products=products)


# ─── Public: Shop ───────────────────────────────────────────────────
@app.route('/shop')
def shop():
    products = Product.query.filter_by(is_active=True).all()
    return render_template('shop.html', products=products)


@app.route('/product/<slug>')
def product_detail(slug):
    product = Product.query.filter_by(slug=slug, is_active=True).first_or_404()
    return render_template('product_detail.html', product=product)


# ─── Cart API ────────────────────────────────────────────────────────
@app.route('/api/cart/add', methods=['POST'])
def cart_add():
    data = request.get_json() or request.form
    variant_id = str(data.get('variant_id'))
    qty = int(data.get('quantity', 1))

    variant = ProductVariant.query.get(int(variant_id))
    if not variant or not variant.is_active:
        return jsonify({'error': 'Product not available'}), 400

    cart = session.get('cart', {})
    if variant_id in cart:
        cart[variant_id]['qty'] += qty
    else:
        cart[variant_id] = {
            'variant_id': int(variant_id),
            'product_name': variant.product.name,
            'size': variant.size,
            'price': variant.price,
            'qty': qty,
            'image_url': variant.product.image_url or ''
        }

    if cart[variant_id]['qty'] > variant.stock:
        cart[variant_id]['qty'] = variant.stock

    session['cart'] = cart
    total_items = sum(item['qty'] for item in cart.values())
    return jsonify({'success': True, 'cart_count': total_items})


@app.route('/api/cart/update', methods=['POST'])
def cart_update():
    data = request.get_json() or request.form
    variant_id = str(data.get('variant_id'))
    qty = int(data.get('quantity', 0))

    cart = session.get('cart', {})
    if variant_id in cart:
        if qty <= 0:
            del cart[variant_id]
        else:
            variant = ProductVariant.query.get(int(variant_id))
            if variant and qty > variant.stock:
                qty = variant.stock
            cart[variant_id]['qty'] = qty

    session['cart'] = cart
    total_items = sum(item['qty'] for item in cart.values())
    subtotal = sum(item['price'] * item['qty'] for item in cart.values())
    return jsonify({'success': True, 'cart_count': total_items, 'subtotal': subtotal})


@app.route('/api/cart/remove', methods=['POST'])
def cart_remove():
    data = request.get_json() or request.form
    variant_id = str(data.get('variant_id'))
    cart = session.get('cart', {})
    cart.pop(variant_id, None)
    session['cart'] = cart
    total_items = sum(item['qty'] for item in cart.values())
    return jsonify({'success': True, 'cart_count': total_items})


@app.route('/cart')
def cart():
    cart_items = session.get('cart', {})
    items = []
    subtotal = 0
    for vid, item in cart_items.items():
        variant = ProductVariant.query.get(int(vid))
        line_total = item['price'] * item['qty']
        subtotal += line_total
        items.append({**item, 'variant_id': vid, 'line_total': line_total,
                      'in_stock': variant.in_stock if variant else False,
                      'max_stock': variant.stock if variant else 0})

    tax = calculate_tax(subtotal)
    return render_template('cart.html', items=items, subtotal=subtotal, tax=tax)


# ─── Checkout ────────────────────────────────────────────────────────
@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart_items = session.get('cart', {})
    if not cart_items:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('shop'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        address = request.form.get('address', '').strip()
        city = request.form.get('city', '').strip()
        state = request.form.get('state', '').strip()
        payment_method = request.form.get('payment_method', 'bank_transfer')
        customer_type = request.form.get('customer_type', 'retail')

        if not all([name, phone, address, state]):
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('checkout'))

        logged_in_customer_id = session.get('customer_id')
        if logged_in_customer_id:
            customer = Customer.query.get(logged_in_customer_id)
            if customer and customer.is_registered:
                customer.name = name
                customer.phone = phone
                if email:
                    customer.email = email
                customer.address = address
                customer.city = city
                customer.state = state
                customer.customer_type = customer_type
            else:
                customer = None

        if not logged_in_customer_id or not customer:
            customer = Customer.query.filter_by(phone=phone).first()
            if not customer:
                customer = Customer(name=name, phone=phone, email=email,
                                  customer_type=customer_type, address=address,
                                  city=city, state=state)
                db.session.add(customer)
                db.session.flush()
            else:
                customer.name = name
                if email:
                    customer.email = email
                customer.address = address
                customer.city = city
                customer.state = state

        subtotal = 0
        order_items = []
        for vid, item in cart_items.items():
            variant = ProductVariant.query.get(int(vid))
            if not variant or variant.stock < item['qty']:
                flash(f'{item["product_name"]} ({item["size"]}) is out of stock.', 'danger')
                return redirect(url_for('cart'))

            unit_price = item['price']
            if customer_type == 'wholesale' and variant.wholesale_price and item['qty'] >= variant.wholesale_min_qty:
                unit_price = variant.wholesale_price

            line_total = unit_price * item['qty']
            subtotal += line_total
            order_items.append({
                'variant': variant, 'qty': item['qty'],
                'unit_price': unit_price, 'line_total': line_total,
                'product_name': item['product_name'], 'size': item['size']
            })

        tax = calculate_tax(subtotal)
        delivery_fee = get_delivery_fee(state)
        total = subtotal + tax + delivery_fee

        order = Order(
            order_number=generate_order_number(),
            customer_id=customer.id,
            delivery_name=name, delivery_phone=phone,
            delivery_address=address, delivery_city=city, delivery_state=state,
            subtotal=subtotal, tax_amount=tax, delivery_fee=delivery_fee,
            total=total, payment_method=payment_method,
            payment_status='unpaid', status='pending'
        )
        db.session.add(order)
        db.session.flush()

        for oi in order_items:
            db.session.add(OrderItem(
                order_id=order.id, variant_id=oi['variant'].id,
                product_name=oi['product_name'], variant_size=oi['size'],
                quantity=oi['qty'], unit_price=oi['unit_price'],
                line_total=oi['line_total']
            ))
            # Deduct stock
            stock_before = oi['variant'].stock
            oi['variant'].stock -= oi['qty']
            db.session.add(InventoryLog(
                variant_id=oi['variant'].id, action='sale',
                quantity_change=-oi['qty'], stock_before=stock_before,
                stock_after=oi['variant'].stock, reference=order.order_number
            ))

        db.session.commit()
        session.pop('cart', None)

        if payment_method == 'paystack':
            return redirect(url_for('order_confirmation', order_number=order.order_number, pay=1))

        return redirect(url_for('order_confirmation', order_number=order.order_number))

    # GET: show checkout form
    items = []
    subtotal = 0
    for vid, item in cart_items.items():
        line_total = item['price'] * item['qty']
        subtotal += line_total
        items.append({**item, 'variant_id': vid, 'line_total': line_total})

    tax = calculate_tax(subtotal)
    delivery_zones = DeliveryZone.query.filter_by(is_active=True).order_by(DeliveryZone.state).all()
    paystack_key = get_setting('paystack_public_key', '')

    checkout_user = None
    customer_id = session.get('customer_id')
    if customer_id:
        checkout_user = Customer.query.get(customer_id)

    return render_template('checkout.html', items=items, subtotal=subtotal, tax=tax,
                         delivery_zones=delivery_zones, paystack_key=paystack_key,
                         checkout_user=checkout_user)


@app.route('/api/delivery-fee')
def api_delivery_fee():
    state = request.args.get('state', '')
    fee = get_delivery_fee(state)
    zone = DeliveryZone.query.filter_by(state=state).first()
    days = zone.estimated_days if zone else '3-5 days'
    return jsonify({'fee': fee, 'estimated_days': days})


# ─── Order Confirmation ─────────────────────────────────────────────
@app.route('/order/<order_number>')
def order_confirmation(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    show_paystack = request.args.get('pay') == '1' and order.payment_method == 'paystack' and order.payment_status != 'paid'
    paystack_key = get_setting('paystack_public_key', '')
    bank_name = get_setting('bank_name', '')
    bank_account_number = get_setting('bank_account_number', '')
    bank_account_name = get_setting('bank_account_name', '')
    return render_template('order_confirmation.html', order=order,
        show_paystack=show_paystack, paystack_key=paystack_key,
        bank_name=bank_name, bank_account_number=bank_account_number,
        bank_account_name=bank_account_name)


# ─── Paystack Verification ──────────────────────────────────────────
@app.route('/api/verify-payment', methods=['POST'])
def verify_payment():
    data = request.get_json()
    reference = data.get('reference', '')
    order_number = data.get('order_number', '')

    if not reference or not order_number:
        return jsonify({'error': 'Missing data'}), 400

    order = Order.query.filter_by(order_number=order_number).first()
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    secret_key = get_setting('paystack_secret_key', '')
    resp = requests.get(
        f'https://api.paystack.co/transaction/verify/{reference}',
        headers={'Authorization': f'Bearer {secret_key}'}
    )

    if resp.status_code == 200:
        result = resp.json()
        if result.get('data', {}).get('status') == 'success':
            amount_paid = result['data']['amount'] / 100
            order.payment_status = 'paid'
            if order.status == 'pending':
                order.status = 'confirmed'
            payment = Payment(
                order_id=order.id, method='paystack', amount=amount_paid,
                reference=reference, paystack_ref=result['data'].get('reference'),
                status='success', verified_at=datetime.utcnow()
            )
            db.session.add(payment)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Payment verified'})

    return jsonify({'error': 'Payment verification failed'}), 400


@app.route('/api/webhooks/paystack', methods=['POST'])
def paystack_webhook():
    secret_key = get_setting('paystack_secret_key', '')
    signature = request.headers.get('x-paystack-signature', '')
    body = request.get_data()

    expected = hmac.new(secret_key.encode(), body, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(signature, expected):
        abort(400)

    payload = request.get_json()
    event = payload.get('event', '')

    if event == 'charge.success':
        data = payload.get('data', {})
        reference = data.get('reference', '')
        amount = data.get('amount', 0) / 100

        payment = Payment.query.filter_by(paystack_ref=reference).first()
        if payment:
            payment.status = 'success'
            payment.verified_at = datetime.utcnow()
            payment.order.payment_status = 'paid'
            if payment.order.status == 'pending':
                payment.order.status = 'confirmed'
            db.session.commit()

    return '', 200


# ─── Order Tracking ─────────────────────────────────────────────────
@app.route('/track', methods=['GET', 'POST'])
def track_order():
    order = None
    my_orders = []
    customer_id = session.get('customer_id')
    if customer_id:
        customer = Customer.query.get(customer_id)
        if customer and customer.is_registered:
            my_orders = Order.query.filter_by(customer_id=customer.id).order_by(Order.created_at.desc()).limit(10).all()

    if request.method == 'POST':
        order_number = request.form.get('order_number', '').strip()
        phone = request.form.get('phone', '').strip()
        if order_number and phone:
            order = Order.query.filter_by(order_number=order_number).first()
            if order and order.delivery_phone != phone:
                order = None
                flash('Order not found. Please check your order number and phone number.', 'danger')
            elif not order:
                flash('Order not found.', 'danger')
    return render_template('track_order.html', order=order, my_orders=my_orders)


# ─── Invoice ─────────────────────────────────────────────────────────
@app.route('/invoice/<order_number>')
def invoice(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    return render_template('invoice.html', order=order)


# ─── Static Pages ───────────────────────────────────────────────────
@app.route('/about')
def about():
    about_text = get_setting('about_text', '')
    return render_template('about.html', about_text=about_text)


@app.route('/contact')
def contact():
    return render_template('contact.html')


# ─── SEO ─────────────────────────────────────────────────────────────
@app.route('/robots.txt')
def robots():
    content = "User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: " + request.url_root + "sitemap.xml"
    return Response(content, mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap():
    pages = [
        {'loc': request.url_root, 'priority': '1.0'},
        {'loc': request.url_root + 'shop', 'priority': '0.9'},
        {'loc': request.url_root + 'about', 'priority': '0.6'},
        {'loc': request.url_root + 'contact', 'priority': '0.6'},
        {'loc': request.url_root + 'track', 'priority': '0.5'},
    ]
    for product in Product.query.filter_by(is_active=True).all():
        pages.append({'loc': request.url_root + f'product/{product.slug}', 'priority': '0.8'})

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for page in pages:
        xml += f'  <url><loc>{page["loc"]}</loc><priority>{page["priority"]}</priority></url>\n'
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')


# ─── Error Handlers ─────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template('base.html', error_code=404, error_message='Page not found'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('base.html', error_code=500, error_message='Something went wrong'), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
