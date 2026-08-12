"""
LLMSQL Seed Database Generator

Creates a realistic ecommerce.db SQLite database with multi-table
relationships and thousands of rows for sales, customers, products,
categories, orders, order items, and product reviews.

Run directly:
    python -m src.database.seed_databases
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = Path("data/ecommerce.db")

CATEGORIES = [
    "Electronics", "Clothing", "Home & Kitchen", "Books",
    "Sports & Outdoors", "Beauty & Personal Care", "Toys & Games",
    "Automotive", "Health & Wellness", "Office Supplies",
]

PRODUCTS = [
    ("Wireless Bluetooth Headphones", "Electronics", 79.99),
    ("USB-C Fast Charger", "Electronics", 24.99),
    ("Mechanical Keyboard", "Electronics", 129.99),
    ("4K Webcam", "Electronics", 89.99),
    ("Portable SSD 1TB", "Electronics", 109.99),
    ("Smart Watch Pro", "Electronics", 249.99),
    ("Noise Cancelling Earbuds", "Electronics", 149.99),
    ("Men's Running Shoes", "Clothing", 89.99),
    ("Women's Yoga Pants", "Clothing", 44.99),
    ("Unisex Hoodie", "Clothing", 54.99),
    ("Thermal Jacket", "Clothing", 119.99),
    ("Cotton T-Shirt Pack (5)", "Clothing", 34.99),
    ("Stainless Steel Cookware Set", "Home & Kitchen", 199.99),
    ("Robot Vacuum Cleaner", "Home & Kitchen", 299.99),
    ("Air Fryer XL", "Home & Kitchen", 129.99),
    ("Coffee Maker Deluxe", "Home & Kitchen", 79.99),
    ("Bestseller Novel Collection", "Books", 29.99),
    ("Programming in Python", "Books", 49.99),
    ("Data Science Handbook", "Books", 39.99),
    ("Yoga Mat Premium", "Sports & Outdoors", 34.99),
    ("Dumbbell Set 30lb", "Sports & Outdoors", 64.99),
    ("Camping Tent 4-Person", "Sports & Outdoors", 159.99),
    ("Moisturizing Face Cream", "Beauty & Personal Care", 22.99),
    ("Electric Toothbrush", "Beauty & Personal Care", 49.99),
    ("Building Blocks Set", "Toys & Games", 39.99),
    ("Board Game Collection", "Toys & Games", 29.99),
    ("Car Phone Mount", "Automotive", 19.99),
    ("Dash Cam HD", "Automotive", 69.99),
    ("Vitamin D Supplements", "Health & Wellness", 14.99),
    ("Protein Powder 2lb", "Health & Wellness", 34.99),
    ("Ergonomic Office Chair", "Office Supplies", 279.99),
    ("Standing Desk Converter", "Office Supplies", 199.99),
    ("Notebook Set (3-pack)", "Office Supplies", 12.99),
]

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer",
    "Michael", "Linda", "David", "Elizabeth", "William", "Barbara",
    "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah",
    "Christopher", "Karen", "Daniel", "Lisa", "Matthew", "Nancy",
    "Aisha", "Wei", "Carlos", "Priya", "Ahmed", "Yuki",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
    "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
    "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
    "Chen", "Singh", "Kim", "Patel", "Nakamura", "Ali",
]

CITIES = [
    ("New York", "NY"), ("Los Angeles", "CA"), ("Chicago", "IL"),
    ("Houston", "TX"), ("Phoenix", "AZ"), ("Philadelphia", "PA"),
    ("San Antonio", "TX"), ("San Diego", "CA"), ("Dallas", "TX"),
    ("San Jose", "CA"), ("Austin", "TX"), ("Jacksonville", "FL"),
    ("Seattle", "WA"), ("Denver", "CO"), ("Boston", "MA"),
]

SHIPPING_STATUSES = ["Pending", "Shipped", "Delivered", "Returned"]
PAYMENT_METHODS = ["Credit Card", "Debit Card", "PayPal", "Apple Pay", "Google Pay"]


def seed() -> str:
    """Create and populate ecommerce.db. Returns the database path."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # ---- Schema ----
    cur.executescript("""
        CREATE TABLE categories (
            category_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL UNIQUE,
            description   TEXT
        );

        CREATE TABLE products (
            product_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            category_id   INTEGER NOT NULL,
            price         REAL NOT NULL,
            stock_qty     INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL,
            FOREIGN KEY (category_id) REFERENCES categories(category_id)
        );

        CREATE TABLE customers (
            customer_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name    TEXT NOT NULL,
            last_name     TEXT NOT NULL,
            email         TEXT NOT NULL UNIQUE,
            city          TEXT,
            state         TEXT,
            joined_at     TEXT NOT NULL
        );

        CREATE TABLE orders (
            order_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id   INTEGER NOT NULL,
            order_date    TEXT NOT NULL,
            total_amount  REAL NOT NULL DEFAULT 0,
            status        TEXT NOT NULL DEFAULT 'Pending',
            payment_method TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );

        CREATE TABLE order_items (
            item_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id      INTEGER NOT NULL,
            product_id    INTEGER NOT NULL,
            quantity      INTEGER NOT NULL DEFAULT 1,
            unit_price    REAL NOT NULL,
            FOREIGN KEY (order_id)   REFERENCES orders(order_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );

        CREATE TABLE reviews (
            review_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id    INTEGER NOT NULL,
            customer_id   INTEGER NOT NULL,
            rating        INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment       TEXT,
            review_date   TEXT NOT NULL,
            FOREIGN KEY (product_id)  REFERENCES products(product_id),
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );
    """)

    # ---- Categories ----
    for cat in CATEGORIES:
        cur.execute(
            "INSERT INTO categories (name, description) VALUES (?, ?)",
            (cat, f"All {cat.lower()} products"),
        )

    # ---- Products ----
    cat_id_map: dict[str, int] = {}
    for row in cur.execute("SELECT category_id, name FROM categories"):
        cat_id_map[row[1]] = row[0]

    random.seed(42)
    base_date = datetime(2025, 1, 1)
    for name, cat, price in PRODUCTS:
        created = base_date + timedelta(days=random.randint(0, 180))
        cur.execute(
            "INSERT INTO products (name, category_id, price, stock_qty, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, cat_id_map[cat], price, random.randint(20, 500), created.isoformat()),
        )

    # ---- Customers ----
    emails_seen: set[str] = set()
    for i in range(200):
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        email = f"{fn.lower()}.{ln.lower()}{i}@example.com"
        if email in emails_seen:
            continue
        emails_seen.add(email)
        city, state = random.choice(CITIES)
        joined = base_date + timedelta(days=random.randint(0, 365))
        cur.execute(
            "INSERT INTO customers (first_name, last_name, email, city, state, joined_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (fn, ln, email, city, state, joined.isoformat()),
        )

    # ---- Orders & Order Items ----
    product_count = len(PRODUCTS)
    customer_ids = [r[0] for r in cur.execute("SELECT customer_id FROM customers")]

    # Generate orders spanning 2025-01 through 2026-08
    order_start = datetime(2025, 1, 1)
    order_end = datetime(2026, 8, 1)
    total_days = (order_end - order_start).days

    for _ in range(2500):
        cid = random.choice(customer_ids)
        order_date = order_start + timedelta(
            days=random.randint(0, total_days),
            hours=random.randint(8, 22),
            minutes=random.randint(0, 59),
        )
        status = random.choices(
            SHIPPING_STATUSES, weights=[10, 20, 60, 10]
        )[0]
        payment = random.choice(PAYMENT_METHODS)

        cur.execute(
            "INSERT INTO orders (customer_id, order_date, total_amount, status, payment_method) "
            "VALUES (?, ?, 0, ?, ?)",
            (cid, order_date.isoformat(), status, payment),
        )
        order_id = cur.lastrowid

        num_items = random.choices([1, 2, 3, 4], weights=[50, 30, 15, 5])[0]
        chosen_products = random.sample(range(1, product_count + 1), min(num_items, product_count))

        order_total = 0.0
        for pid in chosen_products:
            qty = random.randint(1, 3)
            price_row = cur.execute(
                "SELECT price FROM products WHERE product_id = ?", (pid,)
            ).fetchone()
            unit_price = price_row[0]
            cur.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (?, ?, ?, ?)",
                (order_id, pid, qty, unit_price),
            )
            order_total += unit_price * qty

        cur.execute(
            "UPDATE orders SET total_amount = ? WHERE order_id = ?",
            (round(order_total, 2), order_id),
        )

    # ---- Reviews ----
    review_comments = [
        "Great product, highly recommend!",
        "Good value for money.",
        "Decent quality, met expectations.",
        "Could be better, but okay.",
        "Not what I expected, disappointed.",
        "Excellent quality and fast shipping!",
        "Works perfectly, very happy with purchase.",
        "Average product, nothing special.",
        "Fantastic! Will buy again.",
        "Poor quality, broke after a week.",
    ]
    for _ in range(800):
        pid = random.randint(1, product_count)
        cid = random.choice(customer_ids)
        rating = random.choices([1, 2, 3, 4, 5], weights=[5, 10, 20, 35, 30])[0]
        comment = random.choice(review_comments)
        review_date = order_start + timedelta(days=random.randint(30, total_days))
        cur.execute(
            "INSERT INTO reviews (product_id, customer_id, rating, comment, review_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (pid, cid, rating, comment, review_date.isoformat()),
        )

    conn.commit()
    conn.close()

    return str(DB_PATH)


if __name__ == "__main__":
    path = seed()
    print(f"[OK] DataMind AI ecommerce database seeded at: {path}")
