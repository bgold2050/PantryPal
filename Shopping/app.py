from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
import sqlite3
import requests
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import os
from functools import wraps
from collections import defaultdict # Already added, keeping for clarity

app = Flask(__name__)
DATABASE = 'data/inventory.db'
app.secret_key = os.urandom(24)

# --- Spoonacular API Configuration ---
SPOONACULAR_API_KEY = 'abec6d86b3b94464b8ed9e50d73dd043'
SPOONACULAR_BASE_URL = 'https://api.spoonacular.com/recipes/'
# -----------------------------------

# Make datetime.now FUNCTION available in Jinja2 templates
@app.context_processor
def inject_now():
    return {'now_func': datetime.now}

# Custom Jinja2 Filter for Date Parsing
@app.template_filter('parse_date')
def parse_date_filter(date_string, format="%m/%d/%Y"):
    """Parses a date string into a datetime object."""
    if date_string:
        try:
            return datetime.strptime(date_string, format)
        except ValueError:
            return None
    return None

def get_db_connection():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@login_required
def index():
    user_id = session['user_id']
    with get_db_connection() as conn:
        # Total active food items
        total_food_items = conn.execute('''
            SELECT COUNT(id) FROM inventory
            WHERE user_id = ? AND status = 'active' AND quantity > 0
        ''', (user_id,)).fetchone()[0]

        # Items expiring within 3 days
        expiring_soon_items = []
        all_active_items = conn.execute('''
            SELECT name, expiration_date FROM inventory
            WHERE user_id = ? AND status = 'active' AND quantity > 0 AND expiration_date IS NOT NULL
        ''', (user_id,)).fetchall()

        today = datetime.now()
        for item in all_active_items:
            try:
                exp_date_obj = datetime.strptime(item['expiration_date'], '%m/%d/%Y')
                time_until_expiration = exp_date_obj - today
                if timedelta(days=0) <= time_until_expiration <= timedelta(days=3):
                    expiring_soon_items.append(item)
            except ValueError:
                # Handle cases where expiration_date might be malformed
                pass

        num_expiring_soon = len(expiring_soon_items)

        # Items in shopping list (needed)
        shopping_list_needed = conn.execute('''
            SELECT COUNT(id) FROM list
            WHERE user_id = ? AND status = 0
        ''', (user_id,)).fetchone()[0]

        # Items by location (e.g., Fridge, Pantry, Freezer)
        items_by_location = conn.execute('''
            SELECT location, COUNT(id) FROM inventory
            WHERE user_id = ? AND status = 'active' AND quantity > 0
            GROUP BY location
        ''', (user_id,)).fetchall()

        # Convert to dictionary for easier access in template
        location_counts = {row['location']: row['COUNT(id)'] for row in items_by_location}

        # Get top 5 most recent additions
        recent_additions = conn.execute('''
            SELECT name, quantity, unit, location, expiration_date
            FROM inventory
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 5
        ''', (user_id,)).fetchall()

        # Get top 5 most recent removals/uses
        recent_usage = conn.execute('''
            SELECT i.name, ul.action, ul.amount, ul.timestamp
            FROM usage_log ul
            JOIN inventory i ON ul.inventory_id = i.id
            WHERE ul.user_id = ?
            ORDER BY ul.timestamp DESC
            LIMIT 5
        ''', (user_id,)).fetchall()

    return render_template('index.html',
                           total_food_items=total_food_items,
                           num_expiring_soon=num_expiring_soon,
                           expiring_soon_items=expiring_soon_items, # Pass actual items for display
                           shopping_list_needed=shopping_list_needed,
                           location_counts=location_counts,
                           recent_additions=recent_additions,
                           recent_usage=recent_usage)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirmation = request.form['confirmation']

        if not username:
            flash("Username is required.", "danger")
            return render_template('register.html')
        if not password:
            flash("Password is required.", "danger")
            return render_template('register.html')
        if password != confirmation:
            flash("Passwords do not match.", "danger")
            return render_template('register.html')

        with get_db_connection() as conn:
            existing_user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if existing_user:
                flash("Username already exists.", "danger")
                return render_template('register.html')

            password_hash = generate_password_hash(password)
            conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, password_hash))
            conn.commit()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if not username:
            flash("Username is required.", "danger")
            return render_template('login.html')
        if not password:
            flash("Password is required.", "danger")
            return render_template('login.html')

        with get_db_connection() as conn:
            user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for('index'))
        else:
            flash("Invalid username or password.", "danger")
            return render_template('login.html')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        quantity = int(request.form['quantity'])
        unit = request.form['unit']
        location = request.form['location']
        expiration = request.form['expiration']
        user_id = session['user_id']

        if expiration:
            try:
                exp_date_obj = datetime.strptime(expiration, '%Y-%m-%d')
                expiration = exp_date_obj.strftime('%m/%d/%Y')
            except ValueError:
                flash("Invalid expiration date format.", "danger")
                return render_template('add.html')
        else:
            expiration = (datetime.now() + timedelta(days=7)).strftime('%m/%d/%Y')

        with get_db_connection() as conn:
            conn.execute('''
                INSERT INTO inventory (name, category, quantity, unit, location, expiration_date, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, category, quantity, unit, location, expiration, user_id))
            conn.commit()

        flash(f"{name} added to inventory!", "success")
        return redirect(url_for('inventory'))

    return render_template('add.html')

@app.route('/inventory')
@login_required
def inventory():
    location = request.args.get('location')
    sort_by = request.args.get('sort_by', 'name') # Default sort by name
    order = request.args.get('order', 'asc') # Default order ascending
    search_query = request.args.get('search', '').strip() # Get search query
    user_id = session['user_id']

    # Define allowed sort columns and their base order
    allowed_sort_columns = {
        'name': 'name COLLATE NOCASE',
        'expiration_date': 'expiration_date',
        'quantity': 'quantity'
    }

    # Validate sort_by and order
    if sort_by not in allowed_sort_columns:
        sort_by = 'name'
    if order not in ['asc', 'desc']:
        order = 'asc'

    # Construct the ORDER BY clause
    order_by_clause = f"{allowed_sort_columns[sort_by]} {order.upper()}"

    with get_db_connection() as conn:
        query = f'''
            SELECT * FROM inventory
            WHERE status = "active"
              AND quantity > 0
              AND user_id = ?
        '''
        params = [user_id]

        if location:
            query += ' AND location = ?'
            params.append(location)

        # Add search filter
        if search_query:
            query += ' AND name LIKE ?'
            params.append(f'%{search_query}%')

        query += f' ORDER BY {order_by_clause}'

        items = conn.execute(query, params).fetchall()

    return render_template('inventory.html', items=items, location=location, sort_by=sort_by, order=order, search_query=search_query)

@app.route('/use/<int:item_id>', methods=['POST'])
@login_required
def use(item_id):
    amount_used = int(request.form['amount'])
    user_id = session['user_id']

    with get_db_connection() as conn:
        item = conn.execute('SELECT quantity FROM inventory WHERE id = ? AND user_id = ?', (item_id, user_id)).fetchone()
        if not item:
            flash("Item not found or you don't have permission to use it.", "danger")
            return redirect(url_for('inventory'))

        new_quantity = max(0, item['quantity'] - amount_used)

        conn.execute('UPDATE inventory SET quantity = ? WHERE id = ? AND user_id = ?', (new_quantity, item_id, user_id))
        if new_quantity == 0:
            conn.execute('UPDATE inventory SET status = "used" WHERE id = ? AND user_id = ?', (item_id, user_id))

        conn.execute('''
            INSERT INTO usage_log (inventory_id, action, amount, notes, user_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (item_id, 'used', amount_used, '', user_id))

        conn.commit()
    flash("Item quantity updated.", "success")
    return redirect(url_for('inventory'))

@app.route('/history')
@login_required
def history():
    search_query = request.args.get('search', '').strip() # Get search query
    user_id = session['user_id']

    with get_db_connection() as conn:
        query = """
            SELECT * FROM inventory
            WHERE user_id = ?
        """
        params = [user_id]

        # Add search filter
        if search_query:
            query += ' AND name LIKE ?'
            params.append(f'%{search_query}%')

        query += """
            ORDER BY
                CASE status
                    WHEN 'active' THEN 0
                    WHEN 'used' THEN 1
                    WHEN 'expired' THEN 2
                    ELSE 3
                END,
                name COLLATE NOCASE ASC
        """
        items = conn.execute(query, params).fetchall()
    return render_template('history.html', items=items, search_query=search_query)

@app.route('/manually')
@login_required
def manually():
    return render_template('manually.html')

@app.route('/manually/greens')
@login_required
def manually_greens():
    return render_template('manually_greens.html')

@app.route('/manually/fruits')
@login_required
def manually_fruits():
    return render_template('manually_fruits.html')

@app.route('/manually/vegetables')
@login_required
def manually_vegetables():
    return render_template('manually_vegtables.html')

@app.route('/shopping')
@login_required
def shopping_list():
    search_query = request.args.get('search', '').strip() # Get search query
    user_id = session['user_id']

    with get_db_connection() as conn:
        c = conn.cursor()
        query = """
            SELECT * FROM list
            WHERE user_id = ?
        """
        params = [user_id]

        # Add search filter
        if search_query:
            query += ' AND Item LIKE ?'
            params.append(f'%{search_query}%')

        query += """
            ORDER BY status ASC, Item COLLATE NOCASE ASC
        """
        c.execute(query, params)
        items = c.fetchall()
    return render_template("shopping.html", items=items, search_query=search_query)

@app.route('/confirm_add_to_shopping_list', methods=['GET'])
@login_required
def confirm_add_to_shopping_list():
    item_name = request.args.get('item_name')
    return render_template('confirm_add_to_shopping_list.html', item_name=item_name)

@app.route('/add_to_shopping_list', methods=['POST'])
@login_required
def add_to_shopping_list():
    item_name = request.form['item_name']
    quantity = int(request.form['quantity'])
    category = request.form.get('category', 'Uncategorized') # NEW: Get category, default to 'Uncategorized'
    date_added = datetime.now().strftime('%m/%d/%Y %H:%M')
    user_id = session['user_id']

    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO list (Item, Quantity, DateAdded, Category, user_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (item_name, quantity, date_added, category, user_id)) # NEW: Insert category
        conn.commit()
    flash(f"{item_name} added to shopping list!", "success")
    return redirect(url_for('shopping_list'))

@app.route('/add_item_to_shopping_list_final', methods=['POST'])
@login_required
def add_item_to_shopping_list_final():
    item_name = request.form['item_name']
    quantity = int(request.form['quantity'])
    # This route is typically used after removing an item from inventory,
    # so it might not have a category directly from the form.
    # You might want to fetch the category from the original inventory item if possible,
    # or default it. For now, let's default it.
    category = request.form.get('category', 'Uncategorized') # NEW: Get category, default to 'Uncategorized'
    date_added = datetime.now().strftime('%m/%d/%Y %H:%M')
    user_id = session['user_id']

    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO list (Item, Quantity, DateAdded, Category, user_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (item_name, quantity, date_added, category, user_id)) # NEW: Insert category
        conn.commit()
    flash(f"{item_name} added to shopping list!", "success")
    return redirect(url_for('shopping_list'))

@app.route('/lookup_barcode')
@login_required
def lookup_barcode():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"

    try:
        response = requests.get(url)
        data = response.json()

        if data.get("status") == 1:
            product = data.get("product", {})
            item_name = product.get("product_name", "Unknown Item").title()
            return jsonify({"name": item_name})
        else:
            return jsonify({"name": ""})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/confirm', methods=['GET', 'POST'])
@login_required
def confirm():
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        quantity = int(request.form['quantity'])
        unit = request.form['unit']
        location = request.form['location']
        expiration = request.form['expiration']
        user_id = session['user_id']

        if expiration:
            try:
                exp_date_obj = datetime.strptime(expiration, '%Y-%m-%d')
                expiration = exp_date_obj.strftime('%m/%d/%Y')
            except ValueError:
                flash("Invalid expiration date format.", "danger")
                return render_template('complete_item_info.html', name=name)
        else:
            expiration = (datetime.now() + timedelta(days=7)).strftime('%m/%d/%Y')

        with get_db_connection() as conn:
            conn.execute('''
                INSERT INTO inventory (name, category, quantity, unit, location, expiration_date, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, category, quantity, unit, location, expiration, user_id))
            conn.commit()
        flash(f"{name} added to inventory!", "success")
        return redirect(url_for('inventory'))

    name = request.args.get("name", "")
    return render_template('complete_item_info.html', name=name)

@app.route('/redo')
@login_required
def redo():
    return render_template('add.html')

@app.route('/test')
@login_required
def test():
    return render_template('test.html')

@app.route('/lookup_plu')
@login_required
def lookup_plu():
    code = request.args.get('plu')
    if not code:
        return jsonify({"name": ""})

    with sqlite3.connect("data/your_plu_database.db", timeout=10) as conn:
        cur = conn.cursor()
        cur.execute("SELECT Name FROM names WHERE Plu = ?", (code,))
        row = cur.fetchone()

    return jsonify({"name": row[0] if row else ""})

@app.route('/remove', methods=['GET', 'POST'])
@login_required
def remove():
    error = None
    user_id = session['user_id']

    with get_db_connection() as conn:
        if request.method == 'POST':
            item_id = request.form.get('item_id')
            amount = request.form.get('amount')
            add_to_shopping_list = request.form.get('add_to_shopping_list_checkbox')

            if not item_id:
                error = "Please select an item before removing."
            elif not amount or int(amount) < 1:
                error = "Please enter a valid amount to remove."

            if error:
                items = conn.execute('SELECT id, name, quantity FROM inventory WHERE status = "active" AND quantity > 0 AND user_id = ?', (user_id,)).fetchall()
                return render_template('remove.html', items=items, error=error)

            item_to_remove = conn.execute('SELECT name, quantity FROM inventory WHERE id = ? AND user_id = ?', (item_id, user_id)).fetchone()

            if not item_to_remove:
                flash("Item not found or you don't have permission to remove it.", "danger")
                return redirect(url_for('inventory'))

            new_quantity = max(0, item_to_remove['quantity'] - int(amount))

            conn.execute('UPDATE inventory SET quantity = ? WHERE id = ? AND user_id = ?', (new_quantity, item_id, user_id))
            if new_quantity == 0:
                conn.execute('UPDATE inventory SET status = "used" WHERE id = ? AND user_id = ?', (item_id, user_id))

            conn.execute('''
                INSERT INTO usage_log (inventory_id, action, amount, notes, user_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (item_id, 'removed', int(amount), '', user_id))

            conn.commit()

            if add_to_shopping_list == 'yes':
                # When adding from remove, we don't have a category from the form directly.
                # You might want to fetch the category from the original inventory item here
                # or pass it as a hidden field from the remove form if available.
                # For simplicity, we'll let add_item_to_shopping_list_final default it.
                return redirect(url_for('confirm_add_to_shopping_list', item_name=item_to_remove['name']))
            else:
                flash(f"{int(amount)} of {item_to_remove['name']} removed from inventory.", "success")
                return redirect(url_for('inventory'))

        else:
            items = conn.execute('SELECT id, name, quantity FROM inventory WHERE status = "active" AND quantity > 0 AND user_id = ?', (user_id,)).fetchall()
            return render_template('remove.html', items=items)

@app.route('/toggle_status/<item_name>', methods=['POST'])
@login_required
def toggle_status(item_name):
    user_id = session['user_id']
    with get_db_connection() as conn:
        c = conn.cursor()
        # Ensure we select the Category as well for the shopping list display
        c.execute("SELECT status, Category FROM list WHERE Item = ? AND user_id = ?", (item_name, user_id))
        row = c.fetchone()
        if row:
            new_status = 0 if row[0] == 1 else 1
            c.execute("UPDATE list SET status = ? WHERE Item = ? AND user_id = ?", (new_status, item_name, user_id))
            conn.commit()
            flash(f"Shopping list item '{item_name}' status updated.", "info")
        else:
            flash("Shopping list item not found or you don't have permission to modify it.", "danger")

    return redirect(url_for('shopping_list'))

@app.route('/account')
@login_required
def account():
    return render_template('account.html')

@app.route('/change_username', methods=['POST'])
@login_required
def change_username():
    new_username = request.form['new_username']
    current_password = request.form['current_password']
    user_id = session['user_id']

    if not new_username:
        flash("New username cannot be empty.", "danger")
        return redirect(url_for('account'))

    with get_db_connection() as conn:
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

        if not user or not check_password_hash(user['password_hash'], current_password):
            flash("Incorrect current password.", "danger")
            return redirect(url_for('account'))

        existing_user = conn.execute('SELECT * FROM users WHERE username = ? AND id != ?', (new_username, user_id)).fetchone()
        if existing_user:
            flash("Username already taken.", "danger")
            return redirect(url_for('account'))

        conn.execute('UPDATE users SET username = ? WHERE id = ?', (new_username, user_id))
        conn.commit()
        session['username'] = new_username
        flash("Username updated successfully!", "success")
    return redirect(url_for('account'))

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form['current_password']
    new_password = request.form['new_password']
    confirm_new_password = request.form['confirm_new_password']
    user_id = session['user_id']

    if not new_password or not confirm_new_password:
        flash("New password and confirmation cannot be empty.", "danger")
        return redirect(url_for('account'))

    if new_password != confirm_new_password:
        flash("New passwords do not match.", "danger")
        return redirect(url_for('account'))

    with get_db_connection() as conn:
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

        if not user or not check_password_hash(user['password_hash'], current_password):
            flash("Incorrect current password.", "danger")
            return redirect(url_for('account'))

        new_password_hash = generate_password_hash(new_password)
        conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_password_hash, user_id))
        conn.commit()
        flash("Password updated successfully!", "success")
    return redirect(url_for('account'))

# Route to display the move item page
@app.route('/move')
@login_required
def move():
    user_id = session['user_id']
    with get_db_connection() as conn:
        # Fetch only active items with quantity > 0 for the current user
        active_items = conn.execute('''
            SELECT id, name, quantity, unit, location, expiration_date
            FROM inventory
            WHERE status = "active" AND quantity > 0 AND user_id = ?
            ORDER BY name COLLATE NOCASE ASC
        ''', (user_id,)).fetchall()
    return render_template('move.html', active_items=active_items)

# Route to handle the move item form submission
@app.route('/move_item', methods=['POST'])
@login_required
def move_item():
    item_id = request.form.get('item_id')
    new_location = request.form.get('new_location')
    new_expiration = request.form.get('new_expiration') # This will be in YYYY-MM-DD format from the date input
    user_id = session['user_id']

    if not item_id or not new_location:
        flash("Please select an item and a new location.", "danger")
        return redirect(url_for('move'))

    with get_db_connection() as conn:
        # Verify the item belongs to the user and is active
        item = conn.execute('SELECT * FROM inventory WHERE id = ? AND user_id = ? AND status = "active"', (item_id, user_id)).fetchone()

        if not item:
            flash("Item not found or you don't have permission to move it.", "danger")
            return redirect(url_for('move'))

        update_query = 'UPDATE inventory SET location = ?'
        params = [new_location]

        # Handle optional new expiration date
        if new_expiration:
            try:
                # Convert YYYY-MM-DD from form to MM/DD/YYYY for database consistency
                exp_date_obj = datetime.strptime(new_expiration, '%Y-%m-%d')
                formatted_expiration = exp_date_obj.strftime('%m/%d/%Y')
                update_query += ', expiration_date = ?'
                params.append(formatted_expiration)
            except ValueError:
                flash("Invalid new expiration date format. Item moved, but date not updated.", "warning")
                # Continue without updating expiration if format is bad

        update_query += ' WHERE id = ? AND user_id = ?'
        params.extend([item_id, user_id])

        conn.execute(update_query, params)

        # Log the move action
        conn.execute('''
            INSERT INTO usage_log (inventory_id, action, amount, notes, user_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (item_id, 'moved', item['quantity'], f"Moved from {item['location']} to {new_location}", user_id))

        conn.commit()

    flash(f"'{item['name']}' successfully moved to {new_location}!", "success")
    return redirect(url_for('inventory'))

# --- NEW RECIPES ROUTE ---
@app.route('/recipes', methods=['GET', 'POST'])
@login_required
def recipes():
    user_id = session['user_id']
    recipes_data = []
    ingredients_used = []
    search_type = request.args.get('type', 'all') # 'all' or 'expiring_soon'

    with get_db_connection() as conn:
        if search_type == 'expiring_soon':
            # Logic to get expiring soon items (same as in index route)
            expiring_items_raw = conn.execute('''
                SELECT name, expiration_date FROM inventory
                WHERE user_id = ? AND status = 'active' AND quantity > 0 AND expiration_date IS NOT NULL
            ''', (user_id,)).fetchall()

            today = datetime.now()
            expiring_soon_names = []
            for item in expiring_items_raw:
                try:
                    exp_date_obj = datetime.strptime(item['expiration_date'], '%m/%d/%Y')
                    time_until_expiration = exp_date_obj - today
                    if timedelta(days=0) <= time_until_expiration <= timedelta(days=7): # Increased to 7 days for more recipes
                        expiring_soon_names.append(item['name'])
                except ValueError:
                    pass
            ingredients_used = list(set(expiring_soon_names)) # Use set to remove duplicates
            flash(f"Searching recipes using {len(ingredients_used)} expiring ingredients.", "info")

        else: # Default to 'all'
            # Get all active inventory items
            all_items = conn.execute('''
                SELECT name FROM inventory
                WHERE user_id = ? AND status = 'active' AND quantity > 0
            ''', (user_id,)).fetchall()
            ingredients_used = list(set([item['name'] for item in all_items])) # Use set to remove duplicates
            flash(f"Searching recipes using all {len(ingredients_used)} ingredients in your pantry.", "info")

    if ingredients_used:
        # Convert list of ingredients to a comma-separated string
        ingredients_string = ",".join(ingredients_used)

        # Spoonacular API endpoint for finding recipes by ingredients
        url = f"{SPOONACULAR_BASE_URL}findByIngredients"
        params = {
            'apiKey': SPOONACULAR_API_KEY,
            'ingredients': ingredients_string,
            'number': 9,  # Number of recipes to return
            'ranking': 1, # Maximize used ingredients (1) or minimize missing (2)
            'ignorePantry': False # Use ingredients from pantry
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
            recipes_data = response.json()
            if not recipes_data:
                flash("No recipes found with your current ingredients. Try adding more items or adjusting your search.", "warning")

        except requests.exceptions.RequestException as e:
            flash(f"Error fetching recipes: {e}", "danger")
            recipes_data = []
    else:
        flash("No ingredients available to search for recipes. Add some items to your inventory!", "info")

    return render_template('recipes.html', recipes=recipes_data, search_type=search_type)

