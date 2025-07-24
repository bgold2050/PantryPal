-- Create the inventory table
CREATE TABLE inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,           -- e.g., 'fruit', 'vegetable', 'green'
    quantity INTEGER NOT NULL,
    unit TEXT,               -- e.g., 'pint', 'piece', 'head'
    location TEXT,           -- e.g., 'fridge', 'pantry'
    expiration_date TEXT,    -- stored as ISO date string: 'YYYY-MM-DD'
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active' -- 'active', 'used', 'expired'
);

-- Log of every action (add, use, undo, etc.)
CREATE TABLE usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER,
    action TEXT NOT NULL,        -- 'added', 'used', 'corrected'
    amount INTEGER,
    notes TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Optional: separate shopping list
CREATE TABLE shopping_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    quantity INTEGER,
    unit TEXT,
    added_from TEXT,             -- 'manual' or 'auto'
    status TEXT DEFAULT 'to_buy' -- 'to_buy', 'bought'
);
